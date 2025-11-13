package com.example.e_textilesendingserver.service

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

object BridgeStatusStore {
    private val backing = MutableStateFlow<BridgeState>(BridgeState.Idle)
    val state: StateFlow<BridgeState> = backing

    fun update(state: BridgeState) {
        backing.value = state
    }
}
