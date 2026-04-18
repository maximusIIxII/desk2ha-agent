# Prometheus Scrape Configuration

The Desk2HA agent exposes metrics in Prometheus text exposition format at:

```
GET /v1/metrics/prometheus
```

## Quick Start

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: desk2ha
    scrape_interval: 30s
    bearer_token: "YOUR_AGENT_TOKEN"
    static_configs:
      - targets:
          - "192.168.1.100:9693"   # Agent 1
          - "192.168.1.101:9693"   # Agent 2
    metrics_path: /v1/metrics/prometheus
```

## Multi-Agent Fleet

For fleets with many agents, use file-based service discovery:

```yaml
scrape_configs:
  - job_name: desk2ha
    scrape_interval: 30s
    bearer_token_file: /etc/prometheus/desk2ha_token
    file_sd_configs:
      - files:
          - /etc/prometheus/desk2ha_targets.json
    metrics_path: /v1/metrics/prometheus
```

`desk2ha_targets.json`:
```json
[
  {
    "targets": ["192.168.1.100:9693", "192.168.1.101:9693"],
    "labels": {
      "env": "office",
      "team": "engineering"
    }
  }
]
```

## Metric Names

All metrics use the `desk2ha_` prefix. Examples:

| Agent Metric Key | Prometheus Name |
|---|---|
| `system.cpu_usage_percent` | `desk2ha_cpu_usage_percent` |
| `system.ram_usage_percent` | `desk2ha_ram_usage_percent` |
| `battery.level_percent` | `desk2ha_battery_level_percent` |
| `thermals.cpu_package` | `desk2ha_cpu_package_celsius` |
| `fan.cpu_speed` | `desk2ha_fan_cpu_speed_rpm` |

Labels include `device_key` and `hostname` on every metric.

## Grafana Dashboard

Import the metrics into Grafana with these example queries:

```promql
# CPU usage across fleet
desk2ha_cpu_usage_percent

# Battery levels below 20%
desk2ha_battery_level_percent < 20

# CPU temperature over time
rate(desk2ha_cpu_package_celsius[5m])

# Fleet overview: online agents
count(up{job="desk2ha"} == 1)
```

## Authentication

The endpoint requires the same Bearer token as all other `/v1/*` endpoints.
Configure it in the agent's `config.toml`:

```toml
[http]
auth_token = "your-secret-token-here"
```

## Compatibility

Tested with:
- Prometheus 2.45+
- VictoriaMetrics 1.90+
- Grafana Agent / Alloy
- Datadog Agent (OpenMetrics check)
