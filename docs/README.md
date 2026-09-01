# Screenshots

Regenerate with the app running locally on :8000 (or adjust the port):

```bash
python -m app.seed
python -m app.scheduler &          # let it collect a few checks
python -m uvicorn app.web:app --port 8000

chrome --headless=new --hide-scrollbars --window-size=1200,1060 \
  --virtual-time-budget=6000 --screenshot=docs/dashboard.png \
  http://127.0.0.1:8000/
```
