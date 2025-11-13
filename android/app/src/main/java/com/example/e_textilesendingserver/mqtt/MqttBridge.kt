package com.example.e_textilesendingserver.mqtt

import com.example.e_textilesendingserver.core.config.BridgeConfig
import com.example.e_textilesendingserver.util.await
import com.hivemq.client.mqtt.MqttClient
import com.hivemq.client.mqtt.mqtt3.Mqtt3AsyncClient
import com.hivemq.client.mqtt.mqtt3.message.publish.Mqtt3Publish
import java.nio.ByteBuffer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MqttBridge {

    private var client: Mqtt3AsyncClient? = null

    suspend fun connect(config: BridgeConfig) = withContext(Dispatchers.IO) {
        if (client != null) return@withContext
        val mqttClient = MqttClient.builder()
            .useMqttVersion3()
            .identifier(config.clientId)
            .serverHost(config.brokerHost)
            .serverPort(config.brokerPort)
            .automaticReconnectWithDefaultConfig()
            .buildAsync()
        mqttClient.connectWith()
            .keepAlive(30)
            .cleanSession(true)
            .send()
            .await()
        client = mqttClient
    }

    suspend fun publish(
        topic: String,
        payload: ByteArray,
        qos: Int,
        retain: Boolean = false,
    ) = withContext(Dispatchers.IO) {
        val current = client ?: return@withContext
        current.publishWith()
            .topic(topic)
            .qos(qos.toMqttQos())
            .retain(retain)
            .payload(ByteBuffer.wrap(payload))
            .send()
            .await()
    }

    suspend fun subscribe(
        topic: String,
        scope: CoroutineScope,
        callback: suspend (Mqtt3Publish) -> Unit,
    ) = withContext(Dispatchers.IO) {
        val current = client ?: return@withContext
        current.subscribeWith()
            .topicFilter(topic)
            .callback { publish ->
                scope.launch {
                    callback(publish)
                }
            }
            .send()
            .await()
    }

    suspend fun disconnect() = withContext(Dispatchers.IO) {
        client?.disconnect()?.await()
        client = null
    }

    private fun Int.toMqttQos(): com.hivemq.client.mqtt.datatypes.MqttQos = when (this) {
        2 -> com.hivemq.client.mqtt.datatypes.MqttQos.EXACTLY_ONCE
        1 -> com.hivemq.client.mqtt.datatypes.MqttQos.AT_LEAST_ONCE
        else -> com.hivemq.client.mqtt.datatypes.MqttQos.AT_MOST_ONCE
    }
}
