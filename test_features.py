import unittest
from unittest.mock import MagicMock, patch
import json

# Mocking modules
import sys
sys.modules['paho.mqtt.client'] = MagicMock()
sys.modules['app.sensor2'] = MagicMock()

# Patch main to avoid running it on import
with patch('data_receive.main'):
    import data_receive

class TestNewFeatures(unittest.TestCase):
    
    @patch('data_receive.resolve_ip_with_discovery')
    @patch('data_receive.resolve_device_ip')
    @patch('data_receive.send_config_payload')
    def test_log_command_accepted(self, mock_send, mock_resolve_ip, mock_resolve_with_discovery):
        """
        Test that a 'log' command is accepted and processed by execute_command.
        """
        mock_resolve_ip.return_value = "192.168.1.50"
        mock_send.return_value = {"status": "ok"}
        
        cmd = {
            "command_id": "log-test-1",
            "target_dn": "DEVICE001",
            "payload": {
                "log": {"command": "status"}
            }
        }
        
        result = data_receive.execute_command(cmd)
        
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['ip'], "192.168.1.50")
        
        # Verify the payload sent to the device
        args, _ = mock_send.call_args
        sent_ip, sent_payload_str = args
        sent_payload = json.loads(sent_payload_str)
        
        self.assertEqual(sent_ip, "192.168.1.50")
        self.assertIn("log", sent_payload)
        self.assertEqual(sent_payload["log"]["command"], "status")

    @patch('data_receive.resolve_ip_with_discovery')
    @patch('data_receive.resolve_device_ip')
    @patch('data_receive.send_config_payload')
    def test_calibrate_all_command(self, mock_send, mock_resolve_ip, mock_resolve_with_discovery):
        """
        Test that 'calibrate_all' command is accepted.
        """
        mock_resolve_ip.return_value = "192.168.1.50"
        mock_send.return_value = {"status": "ok"}
        
        cmd = {
            "command_id": "calib-test-1",
            "target_dn": "DEVICE001",
            "payload": {
                "calibration": {
                    "command": "calibrate_all",
                    "level": 0.5,
                    "start_time": 1000,
                    "calibration_time": 5000
                }
            }
        }
        
        result = data_receive.execute_command(cmd)
        
        self.assertEqual(result['status'], 'ok')
        
        # Verify payload
        args, _ = mock_send.call_args
        sent_ip, sent_payload_str = args
        sent_payload = json.loads(sent_payload_str)
        
        self.assertIn("calibration", sent_payload)
        self.assertEqual(sent_payload["calibration"]["command"], "calibrate_all")
        self.assertEqual(sent_payload["calibration"]["level"], 0.5)

    def test_unknown_command_raises_error(self):
        """
        Test that an unknown command without config pins raises ConfigCommandError.
        """
        cmd = {
            "command_id": "test-err",
            "target_dn": "DEVICE001",
            "payload": {
                "type": "unknown_thing"
            }
        }
        
        with self.assertRaises(data_receive.ConfigCommandError):
            data_receive.execute_command(cmd)

if __name__ == '__main__':
    unittest.main()
