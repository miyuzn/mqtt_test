package com.example.e_textilesendingserver.core.config

import android.content.Context
import android.content.Context.MODE_PRIVATE
import android.os.Build
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext

/**
 * 简化的配置仓库，后续可接入 DataStore/QR 导入。
 */
class BridgeConfigRepository(context: Context) {

    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
    private val defaultId = buildClientId()
    private val backing = MutableStateFlow(buildInitialConfig())

    val config: StateFlow<BridgeConfig> = backing

    suspend fun update(block: (BridgeConfig) -> BridgeConfig) {
        val updated = block(backing.value)
        backing.value = updated
        withContext(Dispatchers.IO) {
            persist(updated)
        }
    }

    private fun buildInitialConfig(): BridgeConfig {
        val base = BridgeConfig(
            clientId = defaultId,
            configAgentId = "agent-${defaultId.takeLast(6)}",
        )
        val host = prefs.getString(KEY_BROKER_HOST, null)
        val port = prefs.getInt(KEY_BROKER_PORT, -1)
        return base.copy(
            brokerHost = host ?: base.brokerHost,
            brokerPort = if (port > 0) port else base.brokerPort,
        )
    }

    private fun persist(config: BridgeConfig) {
        prefs.edit()
            .putString(KEY_BROKER_HOST, config.brokerHost)
            .putInt(KEY_BROKER_PORT, config.brokerPort)
            .commit()
    }

    private fun buildClientId(): String {
        val model = Build.MODEL.orEmpty().replace("\\s+".toRegex(), "-").lowercase()
        val tail = UUID.randomUUID().toString().takeLast(8)
        return "android-udp-$model-$tail"
    }

    companion object {
        private const val PREFS_NAME = "bridge_config"
        private const val KEY_BROKER_HOST = "broker_host"
        private const val KEY_BROKER_PORT = "broker_port"
    }
}
