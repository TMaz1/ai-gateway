


formatting, from project root
```
python -m black .
```

run to import dependencies from pyproject.toml
```
python -m pip install -e ".[dev]"
```


run tests
```
python -m pytest
```

run project
```
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

access endpoints
```
http://127.0.0.1:8000/docs
```