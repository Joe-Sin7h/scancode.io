.. _command_line_interface:

Command Line Interface
======================

The main entry point is the :guilabel:`scanpipe` command which is available
directly when you are in the activated virtualenv or at this path:
``<scancode.io_root_dir>/bin/scanpipe``


`$ scanpipe --help`
-------------------

Lists all sub-commands available, including Django built-in commands.
ScanPipe's own commands are listed under the ``[scanpipe]`` section::

    $ scanpipe --help
    ...
    [scanpipe]
        add-input
        add-pipeline
        create-project
        graph
        output
        execute
        show-pipeline


`$ scanpipe <subcommand> --help`
--------------------------------

Displays help for the provided sub-command.

For example::

    $ scanpipe create-project --help
    usage: scanpipe create-project [--input-file INPUTS_FILES]
        [--input-url INPUT_URLS] [--pipeline PIPELINES] [--execute] name

    Create a ScanPipe project.

    positional arguments:
      name                  Project name.


`$ scanpipe create-project <name>`
----------------------------------

Creates a ScanPipe project using ``<name>`` as a Project name. The project name
must be unique.

Optional arguments:

- ``--pipeline PIPELINES`` Pipelines names to add on the project.

- ``--input-file INPUTS_FILES`` Input file locations to copy in the :guilabel:`input/`
  work directory.

- ``--input-url INPUT_URLS`` Input URLs to download in the :guilabel:`input/` work
  directory.

- ``--execute`` Execute the pipelines right after project creation.

.. warning::
    Pipelines are added and are executed in order.


`$ scanpipe add-input --project PROJECT [--input-file FILES] [--input-url URLS]`
--------------------------------------------------------------------------------

Adds input files in the project's work directory.

- ``--input-file INPUTS_FILES`` Input file locations to copy in the :guilabel:`input/`
  work directory.

- ``--input-url INPUT_URLS`` Input URLs to download in the :guilabel:`input/` work
  directory.

For example, assuming you have created beforehand a project named "foo", this will
copy ``~/docker/alpine-base.tar`` to the foo project :guilabel:`input/` directory::

    $ scanpipe add-input --project foo --input-file ~/docker/alpine-base.tar

You can also provide URLs of files to be downloaded to the foo project
:guilabel:`input/` directory::

    $ scanpipe add-input --project foo --input-url https://github.com/nexB/scancode.io-tutorial/releases/download/sample-images/30-alpine-nickolashkraus-staticbox-latest.tar

.. note:: Docker images can be provided as input using their Docker reference
    with the ``docker://docker-reference`` syntax. For example::

    $ [...] --input-url docker://redis
    $ [...] --input-url docker://postgres:13
    $ [...] --input-url docker://docker.elastic.co/elasticsearch/elasticsearch-oss:7.10.2

See https://docs.docker.com/engine/reference/builder/ for more details about
references.


`$ scanpipe add-pipeline --project PROJECT PIPELINE_NAME [PIPELINE_NAME ...]`
-----------------------------------------------------------------------------

Adds the ``PIPELINE_NAME`` to a given ``PROJECT``.
You can use more than one ``PIPELINE_NAME`` to add multiple pipelines at once.

.. warning::
    Pipelines are added and are executed in order.

For example, assuming you have created beforehand a project named "foo", this will
add the docker pipeline to your project::

    $ scanpipe add-pipeline --project foo docker


`$ scanpipe execute --project PROJECT`
--------------------------------------

Executes the next pipeline of the ``PROJECT`` project queue.


`$ scanpipe show-pipeline --project PROJECT`
--------------------------------------------

Lists all the pipelines added to the ``PROJECT`` project.


`$ scanpipe status --project PROJECT`
-------------------------------------

Displays status information about the ``PROJECT`` project.

.. note::
    The full logs of each pipeline execution are displayed by default.
    This can be disabled providing the ``--verbosity 0`` option.


`$ scanpipe output --project PROJECT --format {json,csv,xlsx}`
--------------------------------------------------------------

Outputs the ``PROJECT`` results as JSON, CSV or XLSX.
The output files are created in the ``PROJECT`` :guilabel:`output/` directory.


`$ scanpipe graph [PIPELINE_NAME ...]`
--------------------------------------

Generates one or more pipeline graph image as PNG using
`Graphviz <https://graphviz.org/>`_.
The output images are named using the pipeline name with a ``.png`` extension.

Optional arguments:

- ``--list`` Displays a list of all available pipelines.

- ``--output OUTPUT`` Specifies the directory to which the output is written.

.. note::
    By default, output files are created in the current working directory.


`$ scanpipe delete-project --project PROJECT`
---------------------------------------------

Deletes a project and its related work directory.

Optional arguments:

- ``--no-input`` Does not prompt the user for input of any kind.
