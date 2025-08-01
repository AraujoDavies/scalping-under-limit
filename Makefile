format:
	poetry run isort .
	poetry run black .

dev:
	poetry run ipython -i .\main.py


run:
	poetry run python .\main.py