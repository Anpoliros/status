/**
 * @file ecosystem.config.cjs
 * @description PM2 processes for the status collector and read-only web API.
 */
module.exports = {
  apps: [
    {
      name: 'status-worker',
      // Use this repository's explicit runtime, independent of the parent shell.
      script: `${__dirname}/.venv/bin/python`,
      args: '-m backend.status_monitor.worker --config configs/general.json',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
    {
      name: 'status-api',
      // Use this repository's explicit runtime, independent of the parent shell.
      script: `${__dirname}/.venv/bin/python`,
      args: '-m backend.status_monitor.api --config configs/general.json --host 127.0.0.1 --port 18080 --static-dir dist',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
    {
      name: 'status-pusr-worker',
      script: `${__dirname}/.venv/bin/python`,
      args: '-m backend.status_monitor.worker --config configs-pusr/general.json',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
    {
      name: 'status-pusr-api',
      script: `${__dirname}/.venv/bin/python`,
      args: '-m backend.status_monitor.api --config configs-pusr/general.json --host 0.0.0.0 --port 18081 --static-dir dist',
      cwd: __dirname,
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: { PYTHONUNBUFFERED: '1' },
    },
  ],
};
