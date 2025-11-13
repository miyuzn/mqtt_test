package com.example.e_textilesendingserver.service

import com.example.e_textilesendingserver.core.config.BridgeConfig
import com.example.e_textilesendingserver.core.config.BridgeConfigRepository
import com.example.e_textilesendingserver.core.parser.SensorFrame
import com.example.e_textilesendingserver.core.parser.SensorParser
import com.example.e_textilesendingserver.core.parser.toJsonBytes
import com.example.e_textilesendingserver.data.DeviceRegistry
import com.example.e_textilesendingserver.mqtt.MqttBridge
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.math.max
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.coroutineScope
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

        try {
            mqttBridge.connect(config)
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
                launch { subscribeCommands(config, registry, this) }
                udpLoop(config, registry, stats, rawAggregator)
            }
        } catch (ex: Exception) {
            BridgeStatusStore.update(BridgeState.Error(ex.message ?: "发生未知错误"))
        } finally {
            mqttBridge.disconnect()
            if (BridgeStatusStore.state.value !is BridgeState.Error) {
                BridgeStatusStore.update(BridgeState.Idle)
            }
        }
    }

    private suspend fun udpLoop(
        config: BridgeConfig,
        registry: DeviceRegistry,
        stats: StatsTracker,
        rawAggregator: RawAggregator,
    ) = withContext(Dispatchers.IO) {
        val socket = DatagramSocket(null).apply {
            reuseAddress = true
            bind(InetSocketAddress(config.udpListenPort))
            receiveBufferSize = max(receiveBufferSize, config.udpSocketBufferBytes)
        }
        val localForwarder = if (config.udpCopyLocal) DatagramSocket().apply {
            connect(InetSocketAddress(config.localForwardIp, config.localForwardPort))
        } else null

        val buffer = ByteArray(config.udpBufferBytes)
        val datagram = DatagramPacket(buffer, buffer.size)

        try {
            while (scope.isActive) {
                socket.receive(datagram)
                val data = datagram.data.copyOf(datagram.length)
                val address = datagram.address
                stats.onPacketIn()
                localForwarder?.send(DatagramPacket(data, data.size))
                handlePacket(data, address, config, registry, rawAggregator, stats)
            }
        } finally {
            rawAggregator.flushRemaining { topic, payload, count ->
                mqttBridge.publish(topic, payload, config.mqttQos)
                stats.onRawPublished(payloadCount = count)
            }
            socket.close()
            localForwarder?.close()
        }
    }

    private suspend fun handlePacket(
        payload: ByteArray,
        address: InetAddress,
        config: BridgeConfig,
        registry: DeviceRegistry,
        rawAggregator: RawAggregator,
        stats: StatsTracker,
    ) {
        if (config.publishRaw) {
            rawAggregator.enqueue(payload) { topic, body, count ->
                mqttBridge.publish(topic, body, config.mqttQos)
                stats.onRawPublished(count)
            }
        }
        if (config.publishParsed) {
            val frame = parser.parse(payload)
            if (frame != null) {
                val host = address.hostAddress
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
        }
        stats.maybeEmit()
    }

    private suspend fun publishRegistryLoop(config: BridgeConfig, registry: DeviceRegistry) {
        while (scope.isActive) {
            val snapshot = registry.snapshot(config.configAgentId)
            val payload = JSONObject().apply {
                put("agent_id", snapshot.agentId)
                put("device_count", snapshot.deviceCount)
                put("devices", snapshot.devices.map {
                    JSONObject().apply {
                        put("dn", it.dn)
                        put("ip", it.ip)
                        put("last_seen", it.lastSeen)
                    }
                })
                put("timestamp", System.currentTimeMillis())
            }.toString().toByteArray()
            val topic = "${config.configAgentTopic.trimEnd('/')}/${config.configAgentId}"
            mqttBridge.publish(topic, payload, config.mqttQos, retain = true)
            delay(config.registryPublishSec * 1000)
        }
    }

    private suspend fun subscribeCommands(
        config: BridgeConfig,
        registry: DeviceRegistry,
        callbackScope: CoroutineScope,
    ) {
        mqttBridge.subscribe(config.configCmdTopic, callbackScope) { publish ->
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
            callbackScope.launch {
                handleCommand(payload, config, registry)
            }
        }
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

        val reply = sendConfigPayload(targetIp, config.deviceTcpPort, config.deviceTcpTimeoutSec, payloadString)
        publishCommandResult(
            config = config,
            commandId = commandId,
            dn = dn,
            status = "ok",
            ip = targetIp,
            extra = reply,
        )
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

        suspend fun enqueue(
            payload: ByteArray,
            publisher: suspend (topic: String, body: ByteArray, count: Int) -> Unit,
        ) {
            if (!config.publishRaw) return
            if (batch.isEmpty()) {
                batchStart = System.currentTimeMillis()
            }
            batch.add(payload)
            if (shouldFlush()) {
                flush(publisher)
            }
        }

        suspend fun flushRemaining(
            publisher: suspend (topic: String, body: ByteArray, count: Int) -> Unit,
        ) {
            flush(publisher)
        }

        private fun shouldFlush(): Boolean {
            if (batch.size >= config.batchMaxItems) return true
            val elapsed = System.currentTimeMillis() - batchStart
            return elapsed >= config.batchMaxMs
        }

        private suspend fun flush(
            publisher: suspend (topic: String, body: ByteArray, count: Int) -> Unit,
        ) {
            if (batch.isEmpty()) return
            val body = joinBatch()
            publisher(config.topicRaw, body, batch.size)
            batch.clear()
            batchStart = 0L
        }

        private fun joinBatch(): ByteArray {
            if (batch.size == 1 && config.batchSeparator.equals("NONE", true)) {
                return batch.first()
            }
            val separator = if (config.batchSeparator.equals("NL", true)) "\n".toByteArray() else ByteArray(0)
            val total = batch.sumOf { it.size } + separator.size * (batch.size - 1)
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
}
