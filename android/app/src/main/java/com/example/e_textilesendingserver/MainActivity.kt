package com.example.e_textilesendingserver

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.widget.EditText
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.example.e_textilesendingserver.core.config.BridgeConfigRepository
import com.example.e_textilesendingserver.databinding.ActivityMainBinding
import com.example.e_textilesendingserver.provisioning.BleProvisionActivity
import com.example.e_textilesendingserver.provisioning.ProvisioningConstants
import com.example.e_textilesendingserver.service.BridgeService
import com.example.e_textilesendingserver.service.BridgeState
import com.example.e_textilesendingserver.service.BridgeStatusStore
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var configRepository: BridgeConfigRepository

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                startBridgeService()
            } else {
                updateStatus(getString(R.string.status_permission_denied))
            }
        }

    private val provisioningLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                val data = result.data
                if (data?.getBooleanExtra(ProvisioningConstants.EXTRA_RESULT_PROVISIONED, false) == true) {
                    val ssid = data.getStringExtra(ProvisioningConstants.EXTRA_RESULT_SSID).orEmpty()
                    val message = if (ssid.isNotEmpty()) {
                        getString(R.string.provision_result_success, ssid)
                    } else {
                        getString(R.string.provision_title)
                    }
                    updateStatus(message)
                }
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        applyWindowInsets()
        configRepository = BridgeConfigRepository(applicationContext)

        binding.provisionButton.setOnClickListener {
            openProvisioning()
        }
        binding.startButton.setOnClickListener {
            val endpoint = validateBrokerInput() ?: return@setOnClickListener
            lifecycleScope.launch {
                configRepository.update { config ->
                    config.copy(
                        brokerHost = endpoint.first,
                        brokerPort = endpoint.second,
                    )
                }
                requestNotificationPermissionIfNeeded()
            }
        }
        binding.stopButton.setOnClickListener {
            stopService(Intent(this, BridgeService::class.java))
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                BridgeStatusStore.state.collect { state ->
                    updateState(state)
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                configRepository.config.collect { config ->
                    updateBrokerInputs(config.brokerHost, config.brokerPort)
                }
            }
        }
    }

    private fun openProvisioning() {
        val intent = Intent(this, BleProvisionActivity::class.java)
        provisioningLauncher.launch(intent)
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val hasPermission = ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            if (hasPermission) {
                startBridgeService()
            } else {
                permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        } else {
            startBridgeService()
        }
    }

    private fun startBridgeService() {
        val intent = Intent(this, BridgeService::class.java)
        ContextCompat.startForegroundService(this, intent)
    }

    private fun updateState(state: BridgeState) {
        val message = when (state) {
            BridgeState.Idle -> getString(R.string.bridge_state_idle)
            BridgeState.Starting -> getString(R.string.bridge_state_starting)
            is BridgeState.Running -> {
                val m = state.metrics
                getString(
                    R.string.bridge_state_running_template,
                    m.packetsIn,
                    m.parsedPublished,
                    m.rawPublished,
                    m.deviceCount,
                )
            }
            is BridgeState.Error -> getString(R.string.bridge_state_error, state.message)
        }
        updateStatus(message)
    }

    private fun updateStatus(message: String) {
        binding.statusMessage.text = message
    }

    private fun validateBrokerInput(): Pair<String, Int>? {
        val host = binding.brokerHostInput.text?.toString()?.trim().orEmpty()
        val portText = binding.brokerPortInput.text?.toString()?.trim().orEmpty()
        var valid = true

        if (host.isBlank()) {
            binding.brokerHostLayout.error = getString(R.string.error_broker_host_required)
            valid = false
        } else {
            binding.brokerHostLayout.error = null
        }

        val port = portText.toIntOrNull()
        if (port == null || port !in 1..65535) {
            binding.brokerPortLayout.error = getString(R.string.error_broker_port_invalid)
            valid = false
        } else {
            binding.brokerPortLayout.error = null
        }

        return if (valid && port != null) host to port else null
    }

    private fun updateBrokerInputs(host: String, port: Int) {
        setTextIfNeeded(binding.brokerHostInput, host)
        setTextIfNeeded(binding.brokerPortInput, port.toString())
    }

    private fun setTextIfNeeded(view: EditText, newValue: String) {
        if (view.text?.toString() != newValue) {
            view.setText(newValue)
            view.setSelection(newValue.length)
        }
    }

    private fun applyWindowInsets() {
        val initialPadding = Rect(
            binding.root.paddingLeft,
            binding.root.paddingTop,
            binding.root.paddingRight,
            binding.root.paddingBottom,
        )
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, windowInsets ->
            val insets = windowInsets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(
                initialPadding.left,
                initialPadding.top + insets.top,
                initialPadding.right,
                initialPadding.bottom + insets.bottom,
            )
            windowInsets
        }
    }
}
