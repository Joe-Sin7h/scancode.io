# SPDX-License-Identifier: Apache-2.0
#
# http://nexb.com and https://github.com/nexB/scancode.io
# The ScanCode.io software is licensed under the Apache License version 2.0.
# Data generated with ScanCode.io is provided as-is without warranties.
# ScanCode is a trademark of nexB Inc.
#
# You may not use this software except in compliance with the License.
# You may obtain a copy of the License at: http://apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#
# Data Generated with ScanCode.io is provided on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, either express or implied. No content created from
# ScanCode.io should be considered or used as legal advice. Consult an Attorney
# for any legal advice.
#
# ScanCode.io is a free software code scanning tool from nexB Inc. and others.
# Visit https://github.com/nexB/scancode.io for support and download.

# Python version can be specified with `$ PYTHON_EXE=python3.x make conf`
PYTHON_EXE?=python3
MANAGE=bin/python manage.py
ACTIVATE?=. bin/activate;
VIRTUALENV_PYZ=etc/thirdparty/virtualenv.pyz
BLACK_ARGS=--exclude="migrations|data" .
# Do not depend on Python to generate the SECRET_KEY
GET_SECRET_KEY=`base64 /dev/urandom | head -c50`
# Customize with `$ make envfile ENV_FILE=/etc/scancodeio/.env`
ENV_FILE=.env
# Customize with `$ make postgres SCANCODEIO_DB_PASSWORD=YOUR_PASSWORD`
SCANCODEIO_DB_PASSWORD=scancodeio

# Use sudo for postgres, but only on Linux
UNAME := $(shell uname)
ifeq ($(UNAME), Linux)
	SUDO_POSTGRES=sudo -u postgres
else
	SUDO_POSTGRES=
endif

virtualenv:
	@echo "-> Bootstrap the virtualenv with PYTHON_EXE=${PYTHON_EXE}"
	@${PYTHON_EXE} ${VIRTUALENV_PYZ} --never-download --no-periodic-update .

conf: virtualenv
	@echo "-> Install dependencies"
	@${ACTIVATE} pip install -e .

dev: virtualenv
	@echo "-> Configure and install development dependencies"
	@${ACTIVATE} pip install -e .[dev]

envfile:
	@echo "-> Create the .env file and generate a secret key"
	@if test -f ${ENV_FILE}; then echo ".env file exists already"; exit 1; fi
	@mkdir -p $(shell dirname ${ENV_FILE}) && touch ${ENV_FILE}
	@echo SECRET_KEY=\"${GET_SECRET_KEY}\" > ${ENV_FILE}

isort:
	@echo "-> Apply isort changes to ensure proper imports ordering"
	bin/isort .

black:
	@echo "-> Apply black code formatter"
	bin/black ${BLACK_ARGS}

doc8:
	@echo "-> Run doc8 validation"
	@${ACTIVATE} doc8 --max-line-length 100 --ignore-path docs/_build/ --quiet docs/

valid: isort black doc8

check: doc8
	@echo "-> Run pycodestyle (PEP8) validation"
	@${ACTIVATE} pycodestyle --max-line-length=88 --exclude=lib,thirdparty,docs,bin,migrations,settings,data,pipelines,var .
	@echo "-> Run isort imports ordering validation"
	@${ACTIVATE} isort --check-only .
	@echo "-> Run black validation"
	@${ACTIVATE} black --check ${BLACK_ARGS}

clean:
	@echo "-> Clean the Python env"
	rm -rf bin/ lib/ lib64/ include/ build/ dist/ scancodeio.egg-info/ docs/_build/ pip-selfcheck.json pyvenv.cfg
	find . -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete

migrate:
	@echo "-> Apply database migrations"
	${MANAGE} migrate

postgres:
	@echo "-> Configure PostgreSQL database"
	@echo "-> Create database user 'scancodeio'"
	${SUDO_POSTGRES} createuser --no-createrole --no-superuser --login --inherit --createdb scancodeio || true
	${SUDO_POSTGRES} psql -c "alter user scancodeio with encrypted password '${SCANCODEIO_DB_PASSWORD}';" || true
	@echo "-> Drop 'scancodeio' database"
	${SUDO_POSTGRES} dropdb scancodeio || true
	@echo "-> Create 'scancodeio' database"
	${SUDO_POSTGRES} createdb --encoding=utf-8 --owner=scancodeio scancodeio
	@$(MAKE) migrate

sqlite:
	@echo "-> Configure SQLite database"
	@echo SCANCODEIO_DB_ENGINE=\"django.db.backends.sqlite3\" >> ${ENV_FILE}
	@echo SCANCODEIO_DB_NAME=\"sqlite3.db\" >> ${ENV_FILE}
	@$(MAKE) migrate

run:
	${MANAGE} runserver 8001

test:
	@echo "-> Run the test suite"
	${MANAGE} test --noinput

worker:
	bin/celery --app scancodeio worker \
               --loglevel=INFO \
               --concurrency 1 --pool threads \
               --events -Ofair --prefetch-multiplier=1 \
               --soft-time-limit=21600 --time-limit=22000

bump:
	@echo "-> Bump the version"
	bin/bumpver update --no-fetch

docs:
	rm -rf docs/_build/
	@${ACTIVATE} sphinx-build docs/ docs/_build/

.PHONY: virtualenv conf dev envfile install check valid isort clean migrate postgres sqlite run test bump docs
