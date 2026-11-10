PY ?= python3

.PHONY: install data site serve test clean
install:            ## editable install with test deps
	$(PY) -m pip install -e ".[dev]"

data:               ## fetch + process + solar (no site)
	$(PY) -m rdst fetch
	$(PY) -m rdst process
	$(PY) -m rdst solar

site:               ## run every stage and build ./site
	$(PY) -m rdst all

serve: site         ## preview at http://localhost:8000
	$(PY) -m http.server 8000 --directory site

test:
	$(PY) -m pytest -q

clean:
	rm -rf data site
