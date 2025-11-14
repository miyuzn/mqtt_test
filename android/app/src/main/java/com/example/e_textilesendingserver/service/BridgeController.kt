package com.example.e_textilesendingserver.service

import android.util.Log
import com.example.e_textilesendingserver.core.config.BridgeConfig
import com.example.e_textilesendingserver.core.config.BridgeConfigRepository
import com.example.e_textilesendingserver.core.parser.SensorParser
import com.example.e_textilesendingserver.core.parser.toJsonBytes
import com.example.e_textilesendingserver.data.DeviceRegistry
import com.example.e_textilesendingserver.mqtt.MqttBridge
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketException
import java.net.SocketTimeoutException
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.coroutines.coroutineContext
import kotlin.text.Charsets
import org.json.JSONArray
import org.json.JSONObject

class BridgeController(
    private val configRepository: BridgeConfigRepository,
    private val parser: SensorParser = SensorParser(),
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mqttBridge = MqttBridge()
    private var runningJob: Job? = null

    fun start() {
        if (runningJob != null) return
        BridgeStatusStore.update(BridgeState.Starting)
        val job = scope.launch {
            val config = configRepository.config.first()
            runBridge(config)
        }
        job.invokeOnCompletion {
            runningJob = null
        }
        runningJob = job
    }

    fun stop() {
        val job = runningJob ?: return
        scope.launch {
            job.cancelAndJoin()
            BridgeStatusStore.update(BridgeState.Idle)
        }
    }

    private suspend fun runBridge(config: BridgeConfig) = withContext(Dispatchers.IO) {
        val registry = DeviceRegistry(config.registryTtlSec)
        val stats = StatsTracker(config, registry)
        val rawAggregator = RawAggregator(config)
        val packetQueue = PacketQueue(config.queueSize, config.dropOldest)
        val subscriptionManager = GcuSubscriptionManager(config)
        try {
            mqttBridge.connect(config)
            subscriptionManager.start(scope)
            BridgeStatusStore.update(
                BridgeState.Running(
                    BridgeMetrics(
                        packetsIn = 0,
                        parsedPublished = 0,
                        rawPublished = 0,
                        dropped = 0,
                        parseErrors = 0,
                        deviceCount = 0,
                        lastUpdateMillis = System.currentTimeMillis(),
                    )
                )
            )
            kotlinx.coroutines.coroutineScope {
                launch { publishRegistryLoop(config, registry) }
                launch { subscribeCommands(config, registry) }
                launch { udpLoop(config, packetQueue, stats, subscriptionManager) }
                launch { mqttWorker(config, registry, stats, rawAggregator, packetQueue) }
            }
        } catch (ex: CancellationException) {
            throw ex
        } catch (ex: Exception) {
            BridgeStatusStore.update(BridgeState.Error(ex.message ?: "发生未知错误"))
        } finally {
            mqttBridge.disconnect()
            subscriptionManager.stop()
            if (BridgeStatusStore.state.value !is BridgeState.Error) {
                BridgeStatusStore.update(BridgeState.Idle)
            }
        }
    }

    private suspend fun udpLoop(
        config: BridgeConfig,
        packetQueue: PacketQueue,
        stats: StatsTracker,
        subscriptionManager: GcuSubscriptionManager,
    ) = withContext(Dispatchers.IO) {
        val socket = DatagramSocket(null).apply {
            reuseAddress = true
            bind(InetSocketAddress(config.udpListenPort))
            runCatching {
                receiveBufferSize = max(receiveBufferSize, config.udpSocketBufferBytes)
            }.onFailure {
                Log.w(TAG, "Unable to set UDP receive buffer: ${it.message}")
            }
            soTimeout = SOCKET_POLL_TIMEOUT_MS
            kotlin.runCatching { broadcast = true }
        }
        subscriptionManager.bindSocket(socket)
        val localForwarder = if (config.udpCopyLocal) DatagramSocket().apply {
            connect(InetSocketAddress(config.localForwardIp, config.localForwardPort))
        } else null

        val buffer = ByteArray(config.udpBufferBytes)
        val datagram = DatagramPacket(buffer, buffer.size)
        val job = coroutineContext.job

        try {
            while (job.isActive) {
                try {
                    socket.receive(datagram)
                } catch (timeout: SocketTimeoutException) {
                    if (!job.isActive) break
                    continue
                } catch (ex: SocketException) {
                    if (!job.isActive) break else throw ex
                }
                val data = datagram.data.copyOf(datagram.length)
                val address = datagram.address
                runCatching {
                    localForwarder?.send(DatagramPacket(data, data.size))
                }.onFailure {
                    Log.w(TAG, "Local UDP forward failed: ${it.message}")
                }
                if (subscriptionManager.handleIncoming(datagram, data)) {
                    continue
                }
                val offered = packetQueue.offer(UdpPacket(data, address))
                if (!offered) {
                    stats.onDropped()
                }
            }
        } finally {
            runCatching { subscriptionManager.broadcastAll() }
            socket.close()
            localForwarder?.close()
        }
    }

    private suspend fun mqttWorker(
        config: BridgeConfig,
        registry: DeviceRegistry,
        stats: StatsTracker,
        rawAggregator: RawAggregator,
        packetQueue: PacketQueue,
    ) = withContext(Dispatchers.IO) {
        val pollTimeout = max(config.batchMaxMs, PACKET_POLL_TIMEOUT_MS)
        val rawPublisher: suspend (ByteArray, Int) -> Unit = { payload, count ->
            mqttBridge.publish(config.topicRaw, payload, config.mqttQos)
            stats.onRawPublished(count)
        }

        try {
            while (scope.isActive) {
                val packet = packetQueue.poll(pollTimeout)
                if (packet == null) {
                    rawAggregator.flushIfTimedOut(rawPublisher)
                    stats.maybeEmit()
                    continue
                }

                stats.onPacketIn()
                val payload = packet.payload
                if (config.publishRaw) {
                    rawAggregator.enqueue(payload, rawPublisher)
                }

                if (config.publishParsed) {
                    val frame = parser.parse(payload)
                    if (frame != null) {
                        val host = packet.address.hostAddress
                        if (!host.isNullOrBlank()) {
                            registry.record(frame.dn, host)
                        }
                        val topic = "${config.topicParsedPrefix.trimEnd('/')}/${frame.dn}"
                        val jsonBytes = frame.toJsonBytes()
                        mqttBridge.publish(topic, jsonBytes, config.mqttQos)
                        stats.onParsedPublished()
                    } else {
                        stats.onParseError()
                    }
                } else {
                    val metadata = parser.peekMetadata(payload)
                    val host = packet.address.hostAddress
                    if (metadata != null && !host.isNullOrBlank()) {
                        registry.record(metadata.dn, host)
                    }
                }

                rawAggregator.flushIfTimedOut(rawPublisher)
                stats.maybeEmit()
            }
        } finally {
            rawAggregator.flushRemaining(rawPublisher)
        }
    }

    private suspend fun publishRegistryLoop(config: BridgeConfig, registry: DeviceRegistry) {
        while (scope.isActive) {
            val snapshot = registry.snapshot(config.configAgentId)
            val devicesArray = JSONArray().apply {
                snapshot.devices.forEach {
                    put(
                        JSONObject().apply {
                            put("dn", it.dn)
                            put("ip", it.ip)
                            put("last_seen", formatIso(it.lastSeen))
                        }
                    )
                }
            }
            val payload = JSONObject().apply {
                put("agent_id", snapshot.agentId)
                put("device_count", snapshot.deviceCount)
                put("devices", devicesArray)
                put("timestamp", formatIso(System.currentTimeMillis()))
            }.toString().toByteArray()
            val topic = "${config.configAgentTopic.trimEnd('/')}/${config.configAgentId}"
            mqttBridge.publish(topic, payload, config.mqttQos, retain = true)
            delay(config.registryPublishSec * 1000)
        }
    }

    private suspend fun subscribeCommands(
        config: BridgeConfig,
        registry: DeviceRegistry,
    ) {
        mqttBridge.subscribe(config.configCmdTopic, scope) { publish ->
            val payloadBytes = publish.payloadAsBytes
            val payload = runCatching {
                JSONObject(String(payloadBytes, Charsets.UTF_8))
            }.getOrElse {
                publishCommandResult(
                    config = config,
                    commandId = "",
                    status = "error",
                    error = "invalid-json: ${it.message}",
                )
                return@subscribe
            }
            scope.launch {
                handleCommand(payload, config, registry)
            }
        }
        awaitCancellation()
    }

    private suspend fun handleCommand(
        payload: JSONObject,
        config: BridgeConfig,
        registry: DeviceRegistry,
    ) = withContext(Dispatchers.IO) {
        val commandId = payload.optString("command_id", "cmd-${System.currentTimeMillis()}")
        val dn = payload.optString("target_dn", payload.optString("dn"))
        if (dn.isBlank()) {
            publishCommandResult(
                config,
                commandId,
                status = "error",
                error = "target_dn required",
            )
            return@withContext
        }
        val payloadSection = payload.optJSONObject("payload") ?: JSONObject()
        val analog = payload.opt("analog") ?: payloadSection.opt("analog")
        val select = payload.opt("select") ?: payloadSection.opt("select")
        val model = payload.opt("model") ?: payloadSection.opt("model")
        val targetIp = payload.optString("ip")
            .ifBlank { payload.optString("target_ip") }
            .ifBlank { payloadSection.optString("ip") }
            .ifBlank { registry.resolve(dn) ?: "" }
        if (targetIp.isBlank()) {
            publishCommandResult(
                config,
                commandId,
                status = "error",
                dn = dn,
                error = "DN 未关联任何 IP",
            )
            return@withContext
        }
        val payloadString = JSONObject().apply {
            put("analog", analog)
            put("select", select)
            put("model", model)
        }.toString() + "\n"

        try {
            val reply = sendConfigPayload(targetIp, config.deviceTcpPort, config.deviceTcpTimeoutSec, payloadString)
            publishCommandResult(
                config = config,
                commandId = commandId,
                dn = dn,
                status = "ok",
                ip = targetIp,
                extra = reply,
            )
        } catch (ex: Exception) {
            publishCommandResult(
                config = config,
                commandId = commandId,
                dn = dn,
                ip = targetIp,
                status = "error",
                error = "internal-error: ${ex.message}",
            )
        }
    }

    private fun publishCommandResult(
        config: BridgeConfig,
        commandId: String,
        status: String,
        dn: String? = null,
        ip: String? = null,
        error: String? = null,
        extra: JSONObject? = null,
    ) {
        val topic = "${config.configResultTopic.trimEnd('/')}/${config.configAgentId}/$commandId"
        val body = JSONObject().apply {
            put("agent_id", config.configAgentId)
            put("timestamp", System.currentTimeMillis())
            put("status", status)
            put("command_id", commandId)
            put("dn", dn)
            put("ip", ip)
            error?.let { put("error", it) }
            extra?.let { put("reply", it) }
        }.toString().toByteArray()
        scope.launch {
            mqttBridge.publish(topic, body, config.mqttQos)
        }
    }

    private fun sendConfigPayload(
        ip: String,
        port: Int,
        timeoutSec: Double,
        payload: String,
    ): JSONObject {
        val socket = Socket()
        return try {
            socket.soTimeout = (timeoutSec * 1000).toInt()
            socket.connect(InetSocketAddress(ip, port), (timeoutSec * 1000).toInt())
            val out = socket.getOutputStream()
            out.write(payload.toByteArray())
            out.flush()
            val reply = socket.getInputStream().bufferedReader().use { reader ->
                reader.readLine().orEmpty()
            }
            if (reply.isBlank()) {
                JSONObject().apply { put("status", "no-reply") }
            } else {
                try {
                    JSONObject(reply)
                } catch (ex: Exception) {
                    JSONObject().apply { put("raw", reply) }
                }
            }
        } finally {
            kotlin.runCatching { socket.close() }
        }
    }

    private class RawAggregator(
        private val config: BridgeConfig,
    ) {
        private val batch = ArrayList<ByteArray>()
        private var batchStart = 0L
        private val separator = if (config.batchSeparator.equals("NL", true)) "\n".toByteArray() else ByteArray(0)

        suspend fun enqueue(
            payload: ByteArray,
            publisher: suspend (ByteArray, Int) -> Unit,
        ) {
            if (!config.publishRaw) return
            if (batch.isEmpty()) {
                batchStart = System.currentTimeMillis()
            }
            batch.add(payload)
            if (batch.size >= config.batchMaxItems) {
                flush(publisher)
            }
        }

        suspend fun flushIfTimedOut(
            publisher: suspend (ByteArray, Int) -> Unit,
        ) {
            if (batch.isEmpty()) return
            val elapsed = System.currentTimeMillis() - batchStart
            if (elapsed >= config.batchMaxMs) {
                flush(publisher)
            }
        }

        suspend fun flushRemaining(
            publisher: suspend (ByteArray, Int) -> Unit,
        ) {
            flush(publisher)
        }

        private suspend fun flush(
            publisher: suspend (ByteArray, Int) -> Unit,
        ) {
            if (batch.isEmpty() || !config.publishRaw) return
            val body = joinBatch()
            val count = batch.size
            batch.clear()
            batchStart = 0L
            publisher(body, count)
        }

        private fun joinBatch(): ByteArray {
            if (batch.size == 1 && separator.isEmpty()) {
                return batch.first()
            }
            val total = batch.sumOf { it.size } + separator.size * max(batch.size - 1, 0)
            val result = ByteArray(total)
            var offset = 0
            batch.forEachIndexed { index, bytes ->
                System.arraycopy(bytes, 0, result, offset, bytes.size)
                offset += bytes.size
                if (separator.isNotEmpty() && index < batch.lastIndex) {
                    System.arraycopy(separator, 0, result, offset, separator.size)
                    offset += separator.size
                }
            }
            return result
        }
    }

    private class StatsTracker(
        private val config: BridgeConfig,
        private val registry: DeviceRegistry,
    ) {
        private var lastUpdate = 0L
        private var packetsIn = 0L
        private var parsed = 0L
        private var raw = 0L
        private var dropped = 0L
        private var parseErrors = 0L

        fun onPacketIn() {
            packetsIn++
        }

        fun onParsedPublished() {
            parsed++
        }

        fun onRawPublished(payloadCount: Int) {
            raw += payloadCount
        }

        fun onDropped() {
            dropped++
        }

        fun onParseError() {
            parseErrors++
        }

        suspend fun maybeEmit() {
            val now = System.currentTimeMillis()
            if (now - lastUpdate < config.statsIntervalMs) return
            lastUpdate = now
            val deviceCount = registry.activeCount()
            BridgeStatusStore.update(
                BridgeState.Running(
                    BridgeMetrics(
                        packetsIn = packetsIn,
                        parsedPublished = parsed,
                        rawPublished = raw,
                        dropped = dropped,
                        parseErrors = parseErrors,
                        deviceCount = deviceCount,
                        lastUpdateMillis = now,
                    )
                )
            )
        }
    }

    companion object {
        private const val TAG = "BridgeController"
        private const val SOCKET_POLL_TIMEOUT_MS = 500
        private const val PACKET_POLL_TIMEOUT_MS = 100L
        private val ISO_FORMATTER: DateTimeFormatter =
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSXXX").withZone(ZoneOffset.UTC)

        private fun formatIso(millis: Long): String =
            ISO_FORMATTER.format(Instant.ofEpochMilli(millis).atOffset(ZoneOffset.UTC))
    }

    private data class UdpPacket(
        val payload: ByteArray,
        val address: InetAddress,
    )

    private class PacketQueue(
        capacity: Int,
        private val dropOldest: Boolean,
    ) {
        private val queue = ArrayBlockingQueue<UdpPacket>(max(1, capacity))

        fun offer(packet: UdpPacket): Boolean {
            if (queue.offer(packet)) {
                return true
            }
            if (dropOldest) {
                queue.poll()
                return queue.offer(packet)
            }
            return false
        }

        fun poll(timeoutMs: Long): UdpPacket? {
            return try {
                if (timeoutMs <= 0) {
                    queue.poll()
                } else {
                    queue.poll(timeoutMs, TimeUnit.MILLISECONDS)
                }
            } catch (ex: InterruptedException) {
                Thread.currentThread().interrupt()
                null
            }
        }
    }

    private class GcuSubscriptionManager(
        private val config: BridgeConfig,
    ) {
        private data class Session(
            var lastSeen: Long,
            var lastSubscribe: Long,
        )

        private val sessions = linkedMapOf<InetSocketAddress, Session>()
        private val lock = Any()
        private var socket: DatagramSocket? = null
        private var job: Job? = null

        fun start(scope: CoroutineScope) {
            if (!config.gcuEnabled || job != null) return
            job = scope.launch(Dispatchers.IO) {
                val intervalMs = maxOf(config.gcuHeartbeatIntervalSec * 500L, 500L)
                while (isActive) {
                    delay(intervalMs)
                    sendHeartbeats()
                }
            }
        }

        fun stop() {
            job?.cancel()
            job = null
            if (config.gcuBroadcastOnStop) {
                broadcastAll()
            }
            synchronized(lock) {
                sessions.clear()
            }
        }

        fun bindSocket(sock: DatagramSocket) {
            if (!config.gcuEnabled) return
            socket = sock
            kotlin.runCatching { sock.broadcast = true }
        }

        fun handleIncoming(packet: DatagramPacket, payload: ByteArray): Boolean {
            if (!config.gcuEnabled) return false
            val control = decodeControl(payload)
            val addr = InetSocketAddress(packet.address, packet.port)
            val now = System.currentTimeMillis()
            if (control != null) {
                val upper = control.uppercase()
                when (upper) {
                    config.gcuAckToken.uppercase() -> {
                        markSession(addr, now, immediate = false)
                        return true
                    }
                    config.gcuBroadcastToken.uppercase() -> {
                        synchronized(lock) {
                            sessions.remove(addr)
                        }
                        return true
                    }
                }
            }
            markSession(addr, now, immediate = true)
            return false
        }

        fun broadcastAll() {
            if (!config.gcuEnabled) return
            val targets = synchronized(lock) { sessions.keys.toList() }
            targets.forEach { sendCommand(config.gcuBroadcastToken, it) }
        }

        private fun markSession(addr: InetSocketAddress, now: Long, immediate: Boolean) {
            val session = synchronized(lock) {
                sessions.getOrPut(addr) { Session(now, 0L) }.also { it.lastSeen = now }
            }
            maybeSendSubscribe(addr, session, now, immediate)
        }

        private fun maybeSendSubscribe(
            addr: InetSocketAddress,
            session: Session,
            now: Long,
            immediate: Boolean,
        ) {
            val intervalMs = config.gcuHeartbeatIntervalSec * 1000L
            val shouldForce = immediate && session.lastSubscribe == 0L
            if (!shouldForce && now - session.lastSubscribe < intervalMs) {
                return
            }
            session.lastSubscribe = now
            sendCommand(config.gcuSubscribeToken, addr)
        }

        private fun sendHeartbeats() {
            if (!config.gcuEnabled) return
            val now = System.currentTimeMillis()
            val intervalMs = config.gcuHeartbeatIntervalSec * 1000L
            val cutoff = config.gcuFailoverSec * 1000L
            val toSend = mutableListOf<InetSocketAddress>()
            val toRemove = mutableListOf<InetSocketAddress>()
            synchronized(lock) {
                sessions.forEach { (addr, session) ->
                    if (now - session.lastSeen > cutoff) {
                        toRemove.add(addr)
                    } else if (now - session.lastSubscribe >= intervalMs) {
                        session.lastSubscribe = now
                        toSend.add(addr)
                    }
                }
                toRemove.forEach { sessions.remove(it) }
            }
            toSend.forEach { sendCommand(config.gcuSubscribeToken, it) }
        }

        private fun sendCommand(token: String, addr: InetSocketAddress) {
            val bytes = token.toByteArray(Charsets.US_ASCII)
            val packet = DatagramPacket(bytes, bytes.size, addr.address, addr.port)
            kotlin.runCatching { socket?.send(packet) }
        }

        private fun decodeControl(payload: ByteArray): String? {
            if (payload.isEmpty() || payload.size > 64) return null
            if (payload.any { it < 0x20 || it > 0x7E }) return null
            return kotlin.runCatching {
                payload.toString(Charsets.US_ASCII).trim()
            }.getOrNull()?.takeIf { it.isNotEmpty() }
        }
    }
}
