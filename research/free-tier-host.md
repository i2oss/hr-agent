# Free-tier host in 2026: Render vs Railway vs alternatives

Ticket: [#4](https://github.com/i2oss/hr-agent/issues/4). Researched 2026-10-06. Free tiers change often; re-check the linked pages before deploying.

## Bottom line

- **Pick Render's free web service.** It is the only option still free, with no card, always available (not a one-off trial), with native "deploy only after GitHub Actions pass".
- **Accept two limits:** it sleeps after 15 minutes idle (about 30-60 s to wake), and its disk is wiped on every restart/deploy.
- **Design around them:** keep RAM under 512 MB (use an API for embeddings, not a local PyTorch model), build the vector index into the image at deploy time, and warm the site up before graders or the demo video hit it.
- **Fallback if 512 MB proves too tight:** Railway Hobby ($5/month, includes $5 usage) or Google Cloud Run (free quota, but needs a card on file).

## What each host offers free (as of Oct 2026)

| Host | Free compute | Sleeps? / cold start | Build minutes | Persistent disk | Card needed | Verdict |
|---|---|---|---|---|---|---|
| **Render** (free instance, Hobby workspace) | 512 MB RAM, 0.1 CPU; 750 instance-hours/month per workspace | Yes, after 15 min with no traffic; wakes in ~1 min (Python apps typically 30-60 s) | 500 pipeline minutes/month | None: filesystem lost on redeploy, restart or spin-down | No | **Recommended** |
| **Railway** | Trial: $5 one-time credit, 30 days, 1 GB RAM. After that "Free" plan: $1 credit/month, 0.5 GB RAM, 1 vCPU, 0.5 GB volume | Optional "serverless" sleep; $1/month only covers a few days of an always-on 0.5 GB service | Usage-billed | Yes (0.5 GB volume on Free; trial volumes deleted 30 days after credit ends) | No | Not really free; good as $5/month fallback |
| **Hugging Face Spaces** | CPU Basic: 2 vCPU, 16 GB RAM | Sleeps after ~48 h idle | n/a | No (50 GB non-persistent) | n/a | **Docker/Gradio Spaces now need PRO ($9/month)**; only static Spaces free |
| **Koyeb** | 1 free instance: 512 MB, 0.1 vCPU, 2 GB SSD (Frankfurt or Washington DC) | Scales to zero after 1 h idle | n/a | No volumes on free | Yes ($29 pre-auth; new accounts default to $29/mo Pro, can downgrade). Acquired by Mistral Feb 2026 | Risky, card required |
| **Fly.io** | No free tier for new orgs; trial = 2 machine-hours or 7 days | n/a | n/a | Paid volumes | After trial | Out (cheapest always-on ~$2-4/month) |
| **Google Cloud Run** | 180k vCPU-s, 360k GiB-s, 2M requests/month free | Scales to zero; cold start a few seconds | Cloud Build billed separately (has its own free quota) | No (use Cloud Storage) | Yes (billing account required) | Solid but more setup for a non-developer |
| **PythonAnywhere** | 512 MB | Free accounts expire after 1 month unused | n/a | Yes | No | No custom long-running processes; poor fit for FastAPI + MCP |

Also note: Render cut included outbound bandwidth on Hobby from 100 GB to 5 GB/month (new plans April 2026; legacy workspaces migrated 1 Aug 2026). A chat demo uses far less than 5 GB; without a card on file, overage suspends rather than bills.

## Secrets and env vars

- **Render:** env vars and secret files per service in the dashboard (or `render.yaml` with `sync: false` for secrets). Fine for `ANTHROPIC_API_KEY`, `LLM_PROVIDER`, etc.
- **Railway / Cloud Run / HF:** all support secret env vars. No differentiator.

## "Deploy only if GitHub Actions tests pass"

Two ways on Render, both free:

1. **Auto-deploy = "After CI Checks Pass"** (service setting). Render waits for all GitHub checks on the commit; deploys only if every check is success/neutral/skipped. Gotcha: if a commit has *zero* checks, it does not deploy.
2. **Deploy hook from Actions.** Turn auto-deploy Off; store the service's secret Deploy Hook URL as GitHub secret `RENDER_DEPLOY_HOOK_URL`; add a `deploy` job with `needs: test` and `if: github.ref == 'refs/heads/main'` that runs `curl -X POST "$RENDER_DEPLOY_HOOK_URL"`.

**Recommend option 2** for the rubric: the gate is visible in the workflow YAML (test job -> deploy job), easy to screenshot and explain in `deployed.md`. Option 1 is a one-click equivalent if simplicity wins.

Railway has the same idea ("Wait for CI" toggle; deploys move to WAITING, then SKIPPED if a workflow fails), plus `railway up` from Actions with a project token. Cloud Run uses `google-github-actions/deploy-cloudrun` after tests.

## Fit for this project (one Python service + small vector index + MCP server)

- **RAM is the real constraint (512 MB).** FastAPI + a NumPy/FAISS or SQLite index over a few dozen policy docs fits easily. A local `sentence-transformers`/PyTorch embedding model does not. Use a hosted embeddings API, or a small ONNX model (e.g. `fastembed` with bge-small) if staying offline.
- **No persistent disk:** build the index at build time (or commit it), load on startup. Mock Action logs / confirmations live in memory or are written to a file accepting they reset on restart; say so in docs. Free Render Postgres exists but expires after 30 days, so avoid relying on it.
- **MCP server:** run it inside the same service (stdio subprocess launched by the agent, or mounted in the FastAPI app). One service = one free instance, no private networking needed (free Render services cannot receive private network traffic anyway).
- **0.1 CPU** means startup and index load should be quick: keep startup work small so the cold start stays near 30 s, not minutes.
- **Cold start handling:** add a `/health` endpoint; open the site a minute before recording the demo or before submitting; mention the 15-min sleep in `deployed.md` so graders are not surprised. (A cron pinger to keep it awake is possible but eats the 750 h budget and is against the spirit of the free tier; not needed.)

## Sources

- Render free tier: https://render.com/docs/free
- Render auto-deploy "After CI Checks Pass": https://render.com/docs/deploys
- Render deploy hooks + GitHub Actions example: https://render.com/docs/deploy-hooks
- Render new workspace plans: https://render.com/docs/new-workspace-plans
- Render Aug 2026 bandwidth change (third-party, 15 Jul / 6 Aug 2026): https://jwatte.com/blog/render-com-platform-review/
- Free hosting state, Sept 2026 (third-party summary, cross-checked against vendor docs): https://snapdeploy.dev/state-of-free-hosting
- Render cold start 30-60 s for Python (third-party): https://www.kunalganglani.com/blog/render-vs-railway-2026
- Railway free trial: https://docs.railway.com/reference/pricing/free-trial
- Railway plans: https://docs.railway.com/reference/pricing/plans
- Railway Wait for CI: https://docs.railway.com/deployments/github-autodeploys
- Hugging Face Spaces (Docker needs paid plan): https://huggingface.co/docs/hub/spaces-overview
- Koyeb instances: https://www.koyeb.com/docs/reference/instances ; pricing: https://www.koyeb.com/pricing
- Fly.io pricing (no free tier): https://docs.fly.io/about/pricing
- Cloud Run pricing: https://cloud.google.com/run/pricing
