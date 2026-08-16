# 🚀 Free Deployment Guide for Binance Sell Bot

This guide walks you through deploying your Binance Sell Bot **100% free** without any upfront costs.

---

## 🌟 Quick Platform Comparison (All 100% Free)

| Platform | Type | Free Tier Specs | Best For |
| :--- | :--- | :--- | :--- |
| **Render.com** | Cloud Web Service | 750 free hrs/mo, Auto SSL, GitHub CI/CD | ⭐ **Easiest & Quickest setup** |
| **Hugging Face Spaces** | Docker Space | 2 vCPUs, 16GB RAM, Free persistent URL | ⭐ **Best continuous 24/7 uptime** |
| **Koyeb** | Serverless Micro App | 1 Free Nano instance, Global Edge | ⭐ **Fast deployment via Docker/Git** |
| **Cloudflare Tunnel (Local)** | Self-Hosted Tunnel | Uses your machine's hardware & IP | ⭐ **Zero Binance IP ban / low latency** |

---

## Option 1: Deploy on Render.com (Recommended)

Render provides free hosting with automated GitHub builds.

### Step 1: Push Your Code to GitHub
1. Create a **Private** repository on GitHub (e.g., `binance-bot`).
2. Initialize git and push your project (make sure `.env` is **NOT** committed — `.gitignore` already protects it):
   ```bash
   git init
   git add .
   git commit -m "Deploy commit"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/<REPO_NAME>.git
   git push -u origin main
   ```

### Step 2: Create a Web Service on Render
1. Go to [https://render.com](https://render.com) and sign up (Free).
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository.
4. Configure the service settings:
   - **Name**: `binance-sell-bot`
   - **Region**: Frankfurt / Singapore / Oregon (choose closest to Binance servers)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python run.py`
   - **Instance Type**: **Free**

### Step 3: Add Environment Variables
Scroll down to **Environment Variables** and add:
- `FLASK_SECRET_KEY`: *(click Generate or enter a random string)*
- `BINANCE_API_KEY`: `your_binance_api_key`
- `BINANCE_API_SECRET`: `your_binance_api_secret`
- `BINANCE_TESTNET_API_KEY`: `your_testnet_key` *(optional)*
- `BINANCE_TESTNET_API_SECRET`: `your_testnet_secret` *(optional)*
- `N8N_WEBHOOK_URL`: `your_webhook_url` *(optional)*

### Step 4: Deploy
Click **Create Web Service**. Within 2-3 minutes, your bot dashboard will be live at `https://binance-sell-bot-xxxx.onrender.com`!

> 💡 **Keep Alive Tip**: Render free tier sleeps after 15 minutes of inactivity. You can use a free monitoring service like [UptimeRobot](https://uptimerobot.com/) to ping your Render URL every 10 minutes to keep it active 24/7.

---

## Option 2: Deploy on Hugging Face Spaces (Docker - Free 24/7)

Hugging Face Spaces offers a generous free tier (2 vCPU, 16GB RAM) using Docker.

1. Go to [https://huggingface.co/spaces](https://huggingface.co/spaces) and create an account.
2. Click **Create new Space**.
3. Set:
   - **Space name**: `binance-sell-bot`
   - **Space SDK**: **Docker** (Blank)
   - **Space hardware**: Free (2 vCPU, 16GB RAM)
   - **Visibility**: **Private** (Crucial to keep your bot private!)
4. In your Space's **Settings** -> **Variables and secrets**, add your environment variables (`BINANCE_API_KEY`, etc.).
5. Clone your space repository locally or upload all project files (including the provided [`Dockerfile`](file:///f:/binance_boot_v2_final%28deploy%29/Dockerfile)).
6. Hugging Face will automatically build and start the Docker container.

---

## Option 3: Deploy on Koyeb (Free Nano App)

1. Sign up at [https://www.koyeb.com](https://www.koyeb.com).
2. Click **Create App**.
3. Select **GitHub** and pick your repository.
4. Set the builder to **Dockerfile** (it will auto-detect the `Dockerfile`).
5. Under **Environment variables**, input your Binance API credentials and Flask secret key.
6. Select the **Free Nano** tier.
7. Click **Deploy**.

---

## Option 4: Local PC + Free Cloudflare Tunnel (Best for Trading)

If you prefer running the bot on your local computer but want a secure public HTTPS URL to control it from anywhere (phone, tablet, office):

1. Download **Cloudflared** (free from Cloudflare):
   - Windows: `winget install --id Cloudflare.cloudflared`
2. Start your bot locally:
   ```bash
   python run.py
   ```
3. In another terminal, run a free instant tunnel:
   ```bash
   cloudflared tunnel --url http://localhost:5000
   ```
4. Cloudflare will generate a temporary free HTTPS link (e.g., `https://random-words.trycloudflare.com`) giving you instant encrypted remote access to your dashboard!

---

## 🔒 Security Best Practices
1. **Never commit `.env`** to Git repositories.
2. Keep your GitHub repository **Private**.
3. On Binance API Management, ensure API keys:
   - Have **"Enable Spot & Margin Trading"** enabled if placing trades.
   - Have **"Enable Withdrawals"** **DISABLED** (never enable withdrawals for trading bots).
   - If using a dedicated IP or local machine, restrict API key access to your IP address.
