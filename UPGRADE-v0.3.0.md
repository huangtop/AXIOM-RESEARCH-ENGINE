# AXIOM v0.3.0 更新流程

這是從既有 v0.1/v0.2 工作目錄升級到 v0.3.0 的「更新檔案包」，不是完整專案。

## 1. 先備份或建立 Git commit

```bash
git add -A
git commit -m "backup before v0.3.0" || true
```

## 2. 解壓更新包後執行

假設目前終端位於原本的專案根目錄：

```bash
/path/to/AXIOM-v0.3.0-update-only/apply_patch.sh .
```

macOS 也可以把更新包解壓在專案外，再把上面的路徑換成實際位置。

## 3. 重建虛擬環境

```bash
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e '.[dev]'
```

不要略過重新安裝 editable package。先前的錯誤代表測試檔已是 v0.3，但 Python 載入的 `valuation.py` 仍是舊版。

## 4. 驗證順序

```bash
python -c "import axiom_engine; print(axiom_engine.__version__)"
python -c "from axiom_engine.services.valuation import run_valuation_book; print(run_valuation_book.__name__)"
axiom validate
pytest -q
ruff check .
axiom value
axiom build-public
```

版本應顯示 `0.3.0`，第二行應顯示 `run_valuation_book`。

## 5. v0.3 生成檔案

```text
data/generated/executions.json
data/generated/valuation_snapshots.json
data/generated/valuation_books.json
```

這些檔案由 `axiom value` 產生，不包含在更新包內。
