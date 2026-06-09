module.exports = {
  apps: [
    {
      name: "aicost-api",
      cwd: "/opt/aicost/backend",
      script: "/opt/aicost/backend/venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port 8000",
      interpreter: "none",
      env_file: "/opt/aicost/backend/.env.production",
      env: {
        APP_ENV: "production",
        DATABASE_URL: "sqlite:////opt/aicost/data/valuation.db",
        CORS_ALLOW_ORIGINS: "http://124.221.103.75",
      },
    },
  ],
};
