module.exports = {
  apps: [
    {
      name: "yakit-api",
      cwd: "/var/www/yakit_analiz",
      script: "start_api.sh",
      interpreter: "bash",
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 10000,
      wait_ready: true,
      listen_timeout: 15000
    },
    {
      name: "yakit-celery",
      cwd: "/var/www/yakit_analiz",
      script: "start_celery.sh",
      interpreter: "bash",
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 10000,
      wait_ready: true,
      listen_timeout: 15000
    },
    {
      name: "yakit-dashboard",
      cwd: "/var/www/yakit_analiz",
      script: "start_dashboard.sh",
      interpreter: "bash",
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 10000,
      wait_ready: true,
      listen_timeout: 15000
    }
  ]
};
