/**
 * @file ecosystem.config.cjs
 * @description PM2 processes for the status collector and read-only web API.
 */
module.exports = {
  apps: [
    {
      name: 'status-worker',
      // Use the system interpreter instead of inheriting another project's virtualenv.
      script: '/usr/bin/python3',
      args: '-m backend.status_monitor.worker --config config.json',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
    {
      name: 'status-api',
      // Use the system interpreter instead of inheriting another project's virtualenv.
      script: '/usr/bin/python3',
      args: '-m backend.status_monitor.api --config config.json --host 127.0.0.1 --port 18080 --static-dir dist',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
    {
      name: 'status-pusr-worker',
      script: '/usr/bin/python3',
      args: '-m backend.status_monitor.worker --config config-pusr.json',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
    {
      name: 'status-pusr-api',
      script: '/usr/bin/python3',
      args: '-m backend.status_monitor.api --config config-pusr.json --host 127.0.0.1 --port 18081 --static-dir dist',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
  ],
};
