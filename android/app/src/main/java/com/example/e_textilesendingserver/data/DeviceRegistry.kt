package com.example.e_textilesendingserver.data

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class DeviceRegistry(
    private val ttlSeconds: Long,
) {

    private val mutex = Mutex()
    private val entries = linkedMapOf<String, Entry>()

    suspend fun record(dn: String, ip: String) {
        val now = System.currentTimeMillis()
        mutex.withLock {
            entries[dn] = Entry(ip = ip, lastSeen = now)
        }
    }

    suspend fun resolve(dn: String): String? = mutex.withLock {
        val now = System.currentTimeMillis()
        entries[dn]?.takeIf { now - it.lastSeen <= ttlSeconds * 1000 }?.ip
    }

    suspend fun snapshot(agentId: String): RegistrySnapshot = mutex.withLock {
        val now = System.currentTimeMillis()
        val active = entries.filterValues { now - it.lastSeen <= ttlSeconds * 1000 }
        RegistrySnapshot(
            agentId = agentId,
            deviceCount = active.size,
            devices = active.map { (dn, entry) ->
                RegistryEntry(
                    dn = dn,
                    ip = entry.ip,
                    lastSeen = entry.lastSeen,
                )
            }
        )
    }

    suspend fun activeCount(): Int = mutex.withLock {
        val now = System.currentTimeMillis()
        entries.values.count { now - it.lastSeen <= ttlSeconds * 1000 }
    }

    data class RegistrySnapshot(
        val agentId: String,
        val deviceCount: Int,
        val devices: List<RegistryEntry>,
    )

    data class RegistryEntry(
        val dn: String,
        val ip: String,
        val lastSeen: Long,
    )

    private data class Entry(
        val ip: String,
        val lastSeen: Long,
    )
}
