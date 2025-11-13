package com.example.e_textilesendingserver.service

sealed interface BridgeState {
    data object Idle : BridgeState
    data object Starting : BridgeState
    data class Running(val metrics: BridgeMetrics) : BridgeState
    data class Error(val message: String) : BridgeState
}

data class BridgeMetrics(
    val packetsIn: Long,
    val parsedPublished: Long,
    val rawPublished: Long,
    val dropped: Long,
    val parseErrors: Long,
    val deviceCount: Int,
    val lastUpdateMillis: Long,
)
