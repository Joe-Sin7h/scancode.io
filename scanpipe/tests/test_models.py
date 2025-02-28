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

import io
import shutil
import tempfile
import uuid
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock
from unittest import skipIf

from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test import TransactionTestCase
from django.utils import timezone

from scancodeio import __version__ as scancodeio_version
from scanpipe.models import CodebaseResource
from scanpipe.models import DiscoveredPackage
from scanpipe.models import Project
from scanpipe.models import ProjectError
from scanpipe.models import Run
from scanpipe.models import get_project_work_directory
from scanpipe.pipes.fetch import Download
from scanpipe.pipes.input import copy_input
from scanpipe.pipes.input import copy_inputs
from scanpipe.tests import license_policies_index
from scanpipe.tests import mocked_now
from scanpipe.tests import package_data1
from scanpipe.tests.pipelines.do_nothing import DoNothing

scanpipe_app = apps.get_app_config("scanpipe")


class BaseScanPipeModelsTest:
    def setUp(self):
        self.project1 = Project.objects.create(name="Analysis")
        self.project_asgiref = Project.objects.get(name="asgiref")

    def create_run(self, **kwargs):
        return Run.objects.create(
            project=self.project1,
            pipeline_name="pipeline",
            **kwargs,
        )


class ScanPipeModelsTest(BaseScanPipeModelsTest, TestCase):
    data_location = Path(__file__).parent / "data"
    fixtures = [data_location / "asgiref-3.3.0_fixtures.json"]

    def test_scanpipe_project_model_extra_data(self):
        self.assertEqual({}, self.project1.extra_data)
        project1_from_db = Project.objects.get(name=self.project1.name)
        self.assertEqual({}, project1_from_db.extra_data)

    def test_scanpipe_project_model_work_directories(self):
        expected_work_directory = f"projects/analysis-{self.project1.short_uuid}"
        self.assertTrue(self.project1.work_directory.endswith(expected_work_directory))
        self.assertTrue(self.project1.work_path.exists())
        self.assertTrue(self.project1.input_path.exists())
        self.assertTrue(self.project1.output_path.exists())
        self.assertTrue(self.project1.codebase_path.exists())
        self.assertTrue(self.project1.tmp_path.exists())

    def test_scanpipe_get_project_work_directory(self):
        project = Project.objects.create(name="Name with spaces and @£$éæ")
        expected = f"/projects/name-with-spaces-and-e-{project.short_uuid}"
        self.assertTrue(get_project_work_directory(project).endswith(expected))
        self.assertTrue(project.work_directory.endswith(expected))

    def test_scanpipe_project_model_clear_tmp_directory(self):
        new_file_path = self.project1.tmp_path / "file.ext"
        new_file_path.touch()
        self.assertEqual([new_file_path], list(self.project1.tmp_path.glob("*")))

        self.project1.clear_tmp_directory()
        self.assertTrue(self.project1.tmp_path.exists())
        self.assertEqual([], list(self.project1.tmp_path.glob("*")))

    def test_scanpipe_project_model_delete(self):
        work_path = self.project1.work_path
        self.assertTrue(work_path.exists())

        uploaded_file = SimpleUploadedFile("file.ext", content=b"content")
        self.project1.write_input_file(uploaded_file)
        self.project1.add_pipeline("docker")
        resource = CodebaseResource.objects.create(project=self.project1, path="path")
        package = DiscoveredPackage.objects.create(project=self.project1)
        resource.discovered_packages.add(package)

        delete_log = self.project1.delete()
        expected = {
            "scanpipe.CodebaseResource": 1,
            "scanpipe.DiscoveredPackage": 1,
            "scanpipe.DiscoveredPackage_codebase_resources": 1,
            "scanpipe.Project": 1,
            "scanpipe.Run": 1,
        }
        self.assertEqual(expected, delete_log[1])

        self.assertFalse(Project.objects.filter(name=self.project1.name).exists())
        self.assertFalse(work_path.exists())

    def test_scanpipe_project_model_reset(self):
        work_path = self.project1.work_path
        self.assertTrue(work_path.exists())

        uploaded_file = SimpleUploadedFile("file.ext", content=b"content")
        self.project1.write_input_file(uploaded_file)
        self.project1.add_pipeline("docker")
        CodebaseResource.objects.create(project=self.project1, path="path")
        DiscoveredPackage.objects.create(project=self.project1)
        # + run + error

        self.project1.reset()

        self.assertTrue(Project.objects.filter(name=self.project1.name).exists())
        self.assertEqual(0, self.project1.projecterrors.count())
        self.assertEqual(0, self.project1.runs.count())
        self.assertEqual(0, self.project1.discoveredpackages.count())
        self.assertEqual(0, self.project1.codebaseresources.count())

        self.assertTrue(work_path.exists())
        self.assertTrue(self.project1.input_path.exists())
        self.assertEqual(["file.ext"], self.project1.input_root)
        self.assertTrue(self.project1.output_path.exists())
        self.assertTrue(self.project1.codebase_path.exists())
        self.assertTrue(self.project1.tmp_path.exists())

    def test_scanpipe_project_model_inputs_and_input_files_and_input_root(self):
        self.assertEqual([], list(self.project1.inputs()))
        self.assertEqual([], self.project1.input_files)
        self.assertEqual([], self.project1.input_root)

        new_file_path1 = self.project1.input_path / "file.ext"
        new_file_path1.touch()

        new_dir1 = self.project1.input_path / "dir1"
        new_dir1.mkdir(parents=True, exist_ok=True)
        new_file_path2 = new_dir1 / "file2.ext"
        new_file_path2.touch()

        inputs = list(self.project1.inputs())
        expected = [new_dir1, new_file_path1, new_file_path2]
        self.assertEqual(sorted(expected), sorted(inputs))

        expected = ["file.ext", "dir1/file2.ext"]
        self.assertEqual(sorted(expected), sorted(self.project1.input_files))

        expected = ["dir1", "file.ext"]
        self.assertEqual(sorted(expected), sorted(self.project1.input_root))

    @mock.patch("scanpipe.pipes.datetime", mocked_now)
    def test_scanpipe_project_model_get_output_file_path(self):
        filename = self.project1.get_output_file_path("file", "ext")
        self.assertTrue(str(filename).endswith("/output/file-2010-10-10-10-10-10.ext"))

        # get_output_file_path always ensure the work_directory is setup
        shutil.rmtree(self.project1.work_directory)
        self.assertFalse(self.project1.work_path.exists())
        self.project1.get_output_file_path("file", "ext")
        self.assertTrue(self.project1.work_path.exists())

    def test_scanpipe_project_model_get_latest_output(self):
        scan1 = self.project1.get_output_file_path("scancode", "json")
        scan1.write_text("")
        scan2 = self.project1.get_output_file_path("scancode", "json")
        scan2.write_text("")
        summary1 = self.project1.get_output_file_path("summary", "json")
        summary1.write_text("")
        scan3 = self.project1.get_output_file_path("scancode", "json")
        scan3.write_text("")
        summary2 = self.project1.get_output_file_path("summary", "json")
        summary2.write_text("")

        self.assertIsNone(self.project1.get_latest_output("none"))
        self.assertEqual(scan3, self.project1.get_latest_output("scancode"))
        self.assertEqual(summary2, self.project1.get_latest_output("summary"))

    def test_scanpipe_project_model_write_input_file(self):
        self.assertEqual([], self.project1.input_files)

        uploaded_file = SimpleUploadedFile("file.ext", content=b"content")
        self.project1.write_input_file(uploaded_file)

        self.assertEqual(["file.ext"], self.project1.input_files)

    def test_scanpipe_project_model_copy_input_from(self):
        self.assertEqual([], self.project1.input_files)

        _, input_location = tempfile.mkstemp()
        input_filename = Path(input_location).name

        self.project1.copy_input_from(input_location)
        self.assertEqual([input_filename], self.project1.input_files)
        self.assertTrue(Path(input_location).exists())

    def test_scanpipe_project_model_move_input_from(self):
        self.assertEqual([], self.project1.input_files)

        _, input_location = tempfile.mkstemp()
        input_filename = Path(input_location).name

        self.project1.move_input_from(input_location)
        self.assertEqual([input_filename], self.project1.input_files)
        self.assertFalse(Path(input_location).exists())

    def test_scanpipe_project_model_inputs_with_source(self):
        inputs, missing_inputs = self.project1.inputs_with_source
        self.assertEqual([], inputs)
        self.assertEqual({}, missing_inputs)

        uploaded_file = SimpleUploadedFile("file.ext", content=b"content")
        self.project1.add_uploads([uploaded_file])
        self.project1.copy_input_from(self.data_location / "notice.NOTICE")
        self.project1.add_input_source(filename="missing.zip", source="uploaded")

        inputs, missing_inputs = self.project1.inputs_with_source
        expected = [
            {
                "is_file": True,
                "name": "file.ext",
                "size": 7,
                "source": "uploaded",
            },
            {
                "is_file": True,
                "name": "notice.NOTICE",
                "size": 1178,
                "source": "not_found",
            },
        ]

        def sort_by_name(x):
            return x.get("name")

        self.assertEqual(
            sorted(expected, key=sort_by_name), sorted(inputs, key=sort_by_name)
        )
        self.assertEqual({"missing.zip": "uploaded"}, missing_inputs)

    def test_scanpipe_project_model_can_add_input(self):
        self.assertTrue(self.project1.can_add_input)

        run = self.project1.add_pipeline("docker")
        self.project1 = Project.objects.get(uuid=self.project1.uuid)
        self.assertTrue(self.project1.can_add_input)

        run.task_start_date = timezone.now()
        run.save()
        self.project1 = Project.objects.get(uuid=self.project1.uuid)
        self.assertFalse(self.project1.can_add_input)

    def test_scanpipe_project_model_add_input_source(self):
        self.assertEqual({}, self.project1.input_sources)

        self.project1.add_input_source("filename", "source", save=True)
        self.project1.refresh_from_db()
        self.assertEqual({"filename": "source"}, self.project1.input_sources)

    def test_scanpipe_project_model_add_downloads(self):
        file_location = self.data_location / "notice.NOTICE"
        copy_inputs([file_location], self.project1.tmp_path)

        download = Download(
            uri="https://example.com/filename.zip",
            directory="",
            filename="notice.NOTICE",
            path=self.project1.tmp_path / "notice.NOTICE",
            size="",
            sha1="",
            md5="",
        )

        self.project1.add_downloads([download])

        inputs, missing_inputs = self.project1.inputs_with_source
        expected = [
            {
                "is_file": True,
                "name": "notice.NOTICE",
                "size": 1178,
                "source": "https://example.com/filename.zip",
            }
        ]
        self.assertEqual(expected, inputs)
        self.assertEqual({}, missing_inputs)

    def test_scanpipe_project_model_add_uploads(self):
        uploaded_file = SimpleUploadedFile("file.ext", content=b"content")
        self.project1.add_uploads([uploaded_file])

        inputs, missing_inputs = self.project1.inputs_with_source
        expected = [
            {"name": "file.ext", "is_file": True, "size": 7, "source": "uploaded"}
        ]
        self.assertEqual(expected, inputs)
        self.assertEqual({}, missing_inputs)

    def test_scanpipe_project_model_get_next_run(self):
        self.assertEqual(None, self.project1.get_next_run())

        run1 = self.create_run()
        run2 = self.create_run()
        self.assertEqual(run1, self.project1.get_next_run())

        run1.task_start_date = timezone.now()
        run1.save()
        self.assertEqual(run2, self.project1.get_next_run())

        run2.task_start_date = timezone.now()
        run2.save()
        self.assertEqual(None, self.project1.get_next_run())

    def test_scanpipe_project_model_get_latest_failed_run(self):
        self.assertEqual(None, self.project1.get_latest_failed_run())

        run1 = self.create_run()
        run2 = self.create_run()
        self.assertEqual(None, self.project1.get_latest_failed_run())

        run1.task_exitcode = 0
        run1.save()
        self.assertEqual(None, self.project1.get_latest_failed_run())

        run1.task_exitcode = 1
        run1.save()
        self.assertEqual(run1, self.project1.get_latest_failed_run())

        run2.task_exitcode = 0
        run2.save()
        self.assertEqual(run1, self.project1.get_latest_failed_run())

        run2.task_exitcode = 1
        run2.save()
        self.assertEqual(run2, self.project1.get_latest_failed_run())

        run1.task_exitcode = None
        run1.save()
        self.assertEqual(run2, self.project1.get_latest_failed_run())

    def test_scanpipe_run_model_init_task_id(self):
        run1 = Run.objects.create(project=self.project1)
        self.assertIsNone(run1.task_id)

        task_id = uuid.uuid4()
        self.assertEqual(1, run1.init_task_id(task_id))
        self.assertIsNone(run1.task_id)
        run1.refresh_from_db()
        self.assertEqual(task_id, run1.task_id)

        new_id = uuid.uuid4()
        self.assertEqual(0, run1.init_task_id(new_id))
        run1.refresh_from_db()
        self.assertEqual(task_id, run1.task_id)

    def test_scanpipe_run_model_set_scancodeio_version(self):
        run1 = Run.objects.create(project=self.project1)
        self.assertEqual("", run1.scancodeio_version)

        run1.set_scancodeio_version()
        self.assertEqual(scancodeio_version, run1.scancodeio_version)

        with self.assertRaises(ValueError) as cm:
            run1.set_scancodeio_version()
        self.assertIn("Field scancodeio_version already set to", str(cm.exception))

    def test_scanpipe_run_model_pipeline_class_property(self):
        run1 = Run.objects.create(project=self.project1, pipeline_name="do_nothing")
        self.assertEqual(DoNothing, run1.pipeline_class)

    def test_scanpipe_run_model_make_pipeline_instance(self):
        run1 = Run.objects.create(project=self.project1, pipeline_name="do_nothing")
        pipeline_instance = run1.make_pipeline_instance()
        self.assertTrue(isinstance(pipeline_instance, DoNothing))

    def test_scanpipe_run_model_task_execution_time_property(self):
        run1 = self.create_run()

        self.assertIsNone(run1.execution_time)

        run1.task_start_date = datetime(1984, 10, 10, 10, 10, 10, tzinfo=timezone.utc)
        run1.save()
        self.assertIsNone(run1.execution_time)

        run1.task_end_date = datetime(1984, 10, 10, 10, 10, 35, tzinfo=timezone.utc)
        run1.save()
        self.assertEqual(25.0, run1.execution_time)

    def test_scanpipe_run_model_execution_time_for_display_property(self):
        run1 = self.create_run()

        self.assertIsNone(run1.execution_time_for_display)

        run1.task_start_date = datetime(1984, 10, 10, 10, 10, 10, tzinfo=timezone.utc)
        run1.save()
        self.assertIsNone(run1.execution_time_for_display)

        run1.task_end_date = datetime(1984, 10, 10, 10, 10, 35, tzinfo=timezone.utc)
        run1.save()
        self.assertEqual("25 seconds", run1.execution_time_for_display)

        run1.task_end_date = datetime(1984, 10, 10, 10, 12, 35, tzinfo=timezone.utc)
        run1.save()
        self.assertEqual("145 seconds (2.4 minutes)", run1.execution_time_for_display)

        run1.task_end_date = datetime(1984, 10, 10, 11, 12, 35, tzinfo=timezone.utc)
        run1.save()
        self.assertEqual("3745 seconds (1.0 hours)", run1.execution_time_for_display)

    def test_scanpipe_run_model_reset_task_values_method(self):
        run1 = self.create_run(
            task_id=uuid.uuid4(),
            task_start_date=timezone.now(),
            task_end_date=timezone.now(),
            task_exitcode=0,
            task_output="Output",
        )

        run1.reset_task_values()
        self.assertIsNone(run1.task_id)
        self.assertIsNone(run1.task_start_date)
        self.assertIsNone(run1.task_end_date)
        self.assertIsNone(run1.task_exitcode)
        self.assertEqual("", run1.task_output)

    def test_scanpipe_run_model_set_task_started_method(self):
        run1 = self.create_run()

        task_id = uuid.uuid4()
        run1.set_task_started(task_id)

        run1 = Run.objects.get(pk=run1.pk)
        self.assertEqual(task_id, run1.task_id)
        self.assertTrue(run1.task_start_date)
        self.assertFalse(run1.task_end_date)

    def test_scanpipe_run_model_set_task_ended_method(self):
        run1 = self.create_run()

        run1.set_task_ended(exitcode=0, output="output")

        run1 = Run.objects.get(pk=run1.pk)
        self.assertEqual(0, run1.task_exitcode)
        self.assertEqual("output", run1.task_output)
        self.assertTrue(run1.task_end_date)

    def test_scanpipe_run_model_queryset_methods(self):
        now = timezone.now()

        started = self.create_run(task_start_date=now)
        not_started = self.create_run()
        queued = self.create_run(task_id=uuid.uuid4())
        executed = self.create_run(task_start_date=now, task_end_date=now)
        succeed = self.create_run(task_start_date=now, task_exitcode=0)
        failed = self.create_run(task_start_date=now, task_exitcode=1)

        qs = self.project1.runs.started()
        self.assertEqual(4, len(qs))
        self.assertIn(started, qs)
        self.assertIn(executed, qs)
        self.assertIn(succeed, qs)
        self.assertIn(failed, qs)

        qs = self.project1.runs.not_started()
        self.assertEqual([not_started], list(qs))

        qs = self.project1.runs.queued()
        self.assertEqual([queued], list(qs))

        qs = self.project1.runs.executed()
        self.assertEqual([executed], list(qs))

        qs = self.project1.runs.succeed()
        self.assertEqual([succeed], list(qs))

        qs = self.project1.runs.failed()
        self.assertEqual([failed], list(qs))

    def test_scanpipe_run_model_status_property(self):
        now = timezone.now()

        started = self.create_run(task_start_date=now)
        not_started = self.create_run()
        queued = self.create_run(task_id=uuid.uuid4())
        succeed = self.create_run(task_start_date=now, task_exitcode=0)
        failed = self.create_run(task_start_date=now, task_exitcode=1)

        self.assertEqual(Run.Status.RUNNING, started.status)
        self.assertEqual(Run.Status.NOT_STARTED, not_started.status)
        self.assertEqual(Run.Status.QUEUED, queued.status)
        self.assertEqual(Run.Status.SUCCESS, succeed.status)
        self.assertEqual(Run.Status.FAILURE, failed.status)

    def test_scanpipe_run_model_append_to_log(self):
        run1 = self.create_run()

        with self.assertRaises(ValueError):
            run1.append_to_log("multiline\nmessage")

        run1.append_to_log("line1")
        run1.append_to_log("line2", save=True)

        run1.refresh_from_db()
        self.assertEqual("line1\nline2\n", run1.log)

    def test_scanpipe_run_model_profile_method(self):
        run1 = self.create_run()
        self.assertIsNone(run1.profile())

        run1.log = (
            "2021-02-05 12:46:47.63 Pipeline [ScanCodebase] starting\n"
            "2021-02-05 12:46:47.63 Step [copy_inputs_to_codebase_directory] starting\n"
            "2021-02-05 12:46:47.63 Step [copy_inputs_to_codebase_directory]"
            " completed in 0.00 seconds\n"
            "2021-02-05 12:46:47.63 Step [run_extractcode] starting\n"
            "2021-02-05 12:46:48.13 Step [run_extractcode] completed in 0.50 seconds\n"
            "2021-02-05 12:46:48.14 Step [run_scancode] starting\n"
            "2021-02-05 12:46:52.59 Step [run_scancode] completed in 4.45 seconds\n"
            "2021-02-05 12:46:52.59 Step [build_inventory_from_scan] starting\n"
            "2021-02-05 12:46:52.75 Step [build_inventory_from_scan]"
            " completed in 0.16 seconds\n"
            "2021-02-05 12:46:52.75 Step [csv_output] starting\n"
            "2021-02-05 12:46:52.82 Step [csv_output] completed in 0.06 seconds\n"
            "2021-02-05 12:46:52.82 Pipeline completed\n"
        )
        run1.save()
        self.assertIsNone(run1.profile())

        run1.task_exitcode = 0
        run1.save()

        expected = {
            "build_inventory_from_scan": 0.16,
            "copy_inputs_to_codebase_directory": 0.0,
            "csv_output": 0.06,
            "run_extractcode": 0.5,
            "run_scancode": 4.45,
        }
        self.assertEqual(expected, run1.profile())

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(run1.profile(print_results=True))

        expected = (
            "copy_inputs_to_codebase_directory  0.0 seconds 0.0%\n"
            "run_extractcode                    0.5 seconds 9.7%\n"
            "\x1b[41;37mrun_scancode                       4.45 seconds 86.1%\x1b[m\n"
            "build_inventory_from_scan          0.16 seconds 3.1%\n"
            "csv_output                         0.06 seconds 1.2%\n"
        )
        self.assertEqual(expected, output.getvalue())

    def test_scanpipe_codebase_resource_model_methods(self):
        resource = CodebaseResource.objects.create(
            project=self.project1, path="filename.ext"
        )

        self.assertEqual(
            self.project1.codebase_path / resource.path, resource.location_path
        )
        self.assertEqual(
            f"{self.project1.codebase_path}/{resource.path}", resource.location
        )

        with open(resource.location, "w") as f:
            f.write("content")
        self.assertEqual("content\n", resource.file_content)

        package = DiscoveredPackage.objects.create(project=self.project1)
        resource.discovered_packages.add(package)
        self.assertEqual([str(package.uuid)], resource.for_packages)

    def test_scanpipe_codebase_resource_model_file_content(self):
        resource = self.project1.codebaseresources.create(path="filename.ext")

        with open(resource.location, "w") as f:
            f.write("content")
        self.assertEqual("content\n", resource.file_content)

        file_with_long_lines = self.data_location / "decompose_l_u_8hpp_source.html"
        copy_input(file_with_long_lines, self.project1.codebase_path)

        resource.path = "decompose_l_u_8hpp_source.html"
        resource.save()

        line_count = len(resource.file_content.split("\n"))
        self.assertEqual(101, line_count)

    def test_scanpipe_codebase_resource_model_unique_license_expressions(self):
        resource = CodebaseResource(project=self.project1)
        resource.license_expressions = [
            "mit",
            "apache-2.0",
            "apache-2.0",
            "mit AND apache-2.0",
            "gpl-3.0",
        ]
        expected = ["apache-2.0", "gpl-3.0", "mit", "mit AND apache-2.0"]
        self.assertEqual(expected, resource.unique_license_expressions)

    def test_scanpipe_pipes_codebase_resources_inject_licenses_policy(self):
        resource = CodebaseResource(
            licenses=[
                {"key": "mit"},
                {"key": "apache-2.0"},
                {"key": "gpl-3.0"},
            ]
        )

        expected = [
            {"key": "mit", "policy": None},
            {
                "key": "apache-2.0",
                "policy": {
                    "color_code": "#008000",
                    "compliance_alert": "",
                    "label": "Approved License",
                    "license_key": "apache-2.0",
                },
            },
            {
                "key": "gpl-3.0",
                "policy": {
                    "color_code": "#c83025",
                    "compliance_alert": "error",
                    "label": "Prohibited License",
                    "license_key": "gpl-3.0",
                },
            },
        ]

        resource.inject_licenses_policy(license_policies_index)
        self.assertEqual(expected, resource.licenses)

    def test_scanpipe_pipes_scancode_codebase_resources_inject_policy_on_save(self):
        scanpipe_app.license_policies_index = license_policies_index

        resource = CodebaseResource.objects.create(
            project=self.project1, path="file", licenses=[{"key": "gpl-3.0"}]
        )
        expected = [
            {
                "key": "gpl-3.0",
                "policy": {
                    "color_code": "#c83025",
                    "compliance_alert": "error",
                    "label": "Prohibited License",
                    "license_key": "gpl-3.0",
                },
            }
        ]
        self.assertEqual(expected, resource.licenses)

        resource.licenses = [{"key": "not-in-index"}]
        resource.save()
        expected = [{"key": "not-in-index", "policy": None}]
        self.assertEqual(expected, resource.licenses)

        resource.licenses = [{"key": "apache-2.0"}]
        resource.save()
        expected = [
            {
                "key": "apache-2.0",
                "policy": {
                    "color_code": "#008000",
                    "compliance_alert": "",
                    "label": "Approved License",
                    "license_key": "apache-2.0",
                },
            }
        ]
        self.assertEqual(expected, resource.licenses)

    def test_scanpipe_codebase_resource_model_compliance_alert(self):
        scanpipe_app.license_policies_index = license_policies_index
        resource = CodebaseResource.objects.create(project=self.project1, path="file")
        self.assertEqual("", resource.compliance_alert)

        license_key = "bsd-new"
        self.assertNotIn(license_key, scanpipe_app.license_policies_index)
        resource.licenses = [{"key": license_key}]
        resource.save()
        self.assertEqual("missing", resource.compliance_alert)

        license_key = "apache-2.0"
        self.assertIn(license_key, scanpipe_app.license_policies_index)
        resource.licenses = [{"key": license_key}]
        resource.save()
        self.assertEqual("ok", resource.compliance_alert)

        license_key = "mpl-2.0"
        self.assertIn(license_key, scanpipe_app.license_policies_index)
        resource.licenses = [{"key": license_key}]
        resource.save()
        self.assertEqual("warning", resource.compliance_alert)

        license_key = "gpl-3.0"
        self.assertIn(license_key, scanpipe_app.license_policies_index)
        resource.licenses = [{"key": license_key}]
        resource.save()
        self.assertEqual("error", resource.compliance_alert)

        resource.licenses = [
            {"key": "apache-2.0"},
            {"key": "mpl-2.0"},
            {"key": "gpl-3.0"},
        ]
        resource.save()
        self.assertEqual("error", resource.compliance_alert)

    def test_scanpipe_scan_fields_model_mixin_methods(self):
        expected = [
            "copyrights",
            "holders",
            "authors",
            "licenses",
            "license_expressions",
            "emails",
            "urls",
        ]
        self.assertEqual(expected, CodebaseResource.scan_fields())

        resource = CodebaseResource.objects.create(
            project=self.project1, path="filename.ext"
        )

        scan_results = {
            "license_expressions": ["mit"],
            "name": "name",
            "non_resource_field": "value",
        }
        resource.set_scan_results(scan_results, save=True)
        resource.refresh_from_db()
        self.assertEqual("", resource.name)
        self.assertEqual(["mit"], resource.license_expressions)

        resource2 = CodebaseResource.objects.create(project=self.project1, path="file2")
        resource2.copy_scan_results(from_instance=resource, save=True)
        resource.refresh_from_db()
        self.assertEqual(["mit"], resource2.license_expressions)

    def test_scanpipe_codebase_resource_queryset_methods(self):
        CodebaseResource.objects.all().delete()

        file = CodebaseResource.objects.create(
            project=self.project1, type=CodebaseResource.Type.FILE, path="file"
        )
        directory = CodebaseResource.objects.create(
            project=self.project1,
            type=CodebaseResource.Type.DIRECTORY,
            path="directory",
        )
        symlink = CodebaseResource.objects.create(
            project=self.project1, type=CodebaseResource.Type.SYMLINK, path="symlink"
        )

        self.assertTrue(file.is_file)
        self.assertFalse(file.is_dir)
        self.assertFalse(file.is_symlink)

        self.assertFalse(directory.is_file)
        self.assertTrue(directory.is_dir)
        self.assertFalse(directory.is_symlink)

        self.assertFalse(symlink.is_file)
        self.assertFalse(symlink.is_dir)
        self.assertTrue(symlink.is_symlink)

        qs = CodebaseResource.objects.files()
        self.assertEqual(1, len(qs))
        self.assertIn(file, qs)

        qs = CodebaseResource.objects.empty()
        self.assertEqual(3, len(qs))
        file.size = 1
        file.save()
        qs = CodebaseResource.objects.empty()
        self.assertEqual(2, len(qs))
        self.assertNotIn(file, qs)
        file.size = 0
        file.save()
        qs = CodebaseResource.objects.empty()
        self.assertEqual(3, len(qs))

        qs = CodebaseResource.objects.directories()
        self.assertEqual(1, len(qs))
        self.assertIn(directory, qs)

        qs = CodebaseResource.objects.symlinks()
        self.assertEqual(1, len(qs))
        self.assertIn(symlink, qs)

        qs = CodebaseResource.objects.without_symlinks()
        self.assertEqual(2, len(qs))
        self.assertIn(file, qs)
        self.assertIn(directory, qs)
        self.assertNotIn(symlink, qs)

        file.licenses = [{"key": "bsd-new", "name": "BSD-3-Clause"}]
        file.save()
        qs = CodebaseResource.objects.has_licenses()
        self.assertEqual(1, len(qs))
        self.assertIn(file, qs)
        self.assertNotIn(directory, qs)
        self.assertNotIn(symlink, qs)

        qs = CodebaseResource.objects.has_no_licenses()
        self.assertEqual(2, len(qs))
        self.assertNotIn(file, qs)
        self.assertIn(directory, qs)
        self.assertIn(symlink, qs)

        qs = CodebaseResource.objects.unknown_license()
        self.assertEqual(0, len(qs))

        file.license_expressions = ["gpl-3.0", "unknown"]
        file.save()
        qs = CodebaseResource.objects.unknown_license()
        self.assertEqual(1, len(qs))
        self.assertIn(file, qs)

        file.license_expressions = ["unknown AND mit", "gpl-3.0-plus"]
        file.save()
        qs = CodebaseResource.objects.unknown_license()
        self.assertEqual(1, len(qs))
        self.assertIn(file, qs)

        file.license_expressions = ["gpl-3.0-plus OR unknown"]
        file.save()
        qs = CodebaseResource.objects.unknown_license()
        self.assertEqual(1, len(qs))
        self.assertIn(file, qs)

        self.assertEqual(0, CodebaseResource.objects.in_package().count())
        self.assertEqual(3, CodebaseResource.objects.not_in_package().count())

        file.create_and_add_package(package_data1)
        self.assertEqual(1, CodebaseResource.objects.in_package().count())
        self.assertEqual(2, CodebaseResource.objects.not_in_package().count())

    def test_scanpipe_codebase_resource_queryset_licenses_categories(self):
        CodebaseResource.objects.all().delete()

        resource1 = CodebaseResource.objects.create(
            project=self.project1,
            path="1",
            licenses=[{"key": "gpl-3.0", "category": "Copyleft"}],
        )

        resource2 = CodebaseResource.objects.create(
            project=self.project1,
            path="2",
            licenses=[{"key": "lgpl-3.0-plus", "category": "Copyleft Limited"}],
        )

        resource_qs = self.project1.codebaseresources

        categories = ["Permissive"]
        self.assertQuerysetEqual([], resource_qs.licenses_categories(categories))

        categories = ["Copyleft"]
        expected = [resource1]
        self.assertQuerysetEqual(expected, resource_qs.licenses_categories(categories))

        categories = ["Copyleft Limited"]
        expected = [resource2]
        self.assertQuerysetEqual(expected, resource_qs.licenses_categories(categories))

        categories = ["Copyleft", "Copyleft Limited"]
        expected = [resource1, resource2]
        self.assertQuerysetEqual(expected, resource_qs.licenses_categories(categories))

    def test_scanpipe_codebase_resource_queryset_json_field_contains(self):
        resource1 = CodebaseResource.objects.create(project=self.project1, path="1")
        resource1.holders = [
            {"value": "H1", "end_line": 51, "start_line": 50},
            {"value": "H2", "end_line": 61, "start_line": 60},
        ]
        resource1.save()

        resource2 = CodebaseResource.objects.create(project=self.project1, path="2")
        resource2.holders = [{"value": "H3", "end_line": 558, "start_line": 556}]
        resource2.save()

        qs = CodebaseResource.objects
        self.assertQuerysetEqual([resource2], qs.json_field_contains("holders", "H3"))
        self.assertQuerysetEqual([resource1], qs.json_field_contains("holders", "H1"))
        expected = [resource1, resource2]
        self.assertQuerysetEqual(expected, qs.json_field_contains("holders", "H"))

    def test_scanpipe_codebase_resource_descendants(self):
        path = "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref"
        resource = self.project_asgiref.codebaseresources.get(path=path)
        descendants = list(resource.descendants())
        self.assertEqual(9, len(descendants))
        self.assertNotIn(resource.path, descendants)
        expected = [
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/__init__.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/compatibility.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/"
            "current_thread_executor.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/local.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/server.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/sync.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/testing.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/timeout.py",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref/wsgi.py",
        ]
        self.assertEqual(expected, sorted([resource.path for resource in descendants]))

    def test_scanpipe_codebase_resource_children(self):
        resource = self.project_asgiref.codebaseresources.get(path="codebase")
        children = list(resource.children())
        self.assertEqual(2, len(children))
        self.assertNotIn(resource.path, children)
        expected = [
            "codebase/asgiref-3.3.0-py3-none-any.whl",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract",
        ]
        self.assertEqual(expected, [resource.path for resource in children])

        path = "codebase/asgiref-3.3.0-py3-none-any.whl-extract"
        resource = self.project_asgiref.codebaseresources.get(path=path)
        children = list(resource.children())
        self.assertEqual(2, len(children))
        self.assertNotIn(resource.path, children)
        expected = [
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref",
            "codebase/asgiref-3.3.0-py3-none-any.whl-extract/asgiref-3.3.0.dist-info",
        ]
        self.assertEqual(expected, [resource.path for resource in children])

    def test_scanpipe_codebase_resource_create_and_add_package(self):
        codebase_resource = CodebaseResource.objects.create(
            project=self.project1, path="filename.ext"
        )
        package = codebase_resource.create_and_add_package(package_data1)
        self.assertEqual(self.project1, package.project)
        self.assertEqual("pkg:deb/debian/adduser@3.118?arch=all", str(package))
        self.assertEqual(1, codebase_resource.discovered_packages.count())
        self.assertEqual(package, codebase_resource.discovered_packages.get())

    def test_scanpipe_discovered_package_model_queryset_methods(self):
        DiscoveredPackage.create_from_data(self.project1, package_data1)
        inputs = [
            ("pkg:deb/debian/adduser@3.118?arch=all", 1),
            ("pkg:deb/debian/adduser@3.118", 1),
            ("pkg:deb/debian/adduser", 1),
            ("pkg:deb/debian", 0),
            ("pkg:deb/debian/adduser@4", 0),
        ]

        for purl, expected_count in inputs:
            qs = DiscoveredPackage.objects.for_package_url(purl)
            self.assertEqual(expected_count, qs.count(), msg=purl)


class ScanPipeModelsTransactionTest(TransactionTestCase):
    """
    Since we are testing some Database errors, we need to use a
    TransactionTestCase to avoid any TransactionManagementError while running
    the tests.
    """

    @mock.patch("scanpipe.models.Run.execute_task_async")
    def test_scanpipe_project_model_add_pipeline(self, mock_execute_task):
        project1 = Project.objects.create(name="Analysis")

        self.assertEqual(0, project1.runs.count())

        pipeline_name = "docker"
        pipeline_class = scanpipe_app.pipelines.get(pipeline_name)
        project1.add_pipeline(pipeline_name)

        self.assertEqual(1, project1.runs.count())
        run = project1.runs.get()
        self.assertEqual(pipeline_name, run.pipeline_name)
        self.assertEqual(pipeline_class.get_doc(), run.description)
        mock_execute_task.assert_not_called()

        project1.add_pipeline(pipeline_name, execute_now=True)
        mock_execute_task.assert_called_once()

    def test_scanpipe_project_model_add_error(self):
        project1 = Project.objects.create(name="Analysis")
        error = project1.add_error(Exception("Error message"), model="Package")
        self.assertEqual(error, ProjectError.objects.get())
        self.assertEqual("Package", error.model)
        self.assertEqual({}, error.details)
        self.assertEqual("Error message", error.message)
        self.assertEqual("", error.traceback)

    def test_scanpipe_project_model_update_extra_data(self):
        project1 = Project.objects.create(name="Analysis")
        self.assertEqual({}, project1.extra_data)

        with self.assertRaises(ValueError):
            project1.update_extra_data("not_a_dict")

        data = {"key": "value"}
        project1.update_extra_data(data)
        self.assertEqual(data, project1.extra_data)
        project1.refresh_from_db()
        self.assertEqual(data, project1.extra_data)

        more_data = {"more": "data"}
        project1.update_extra_data(more_data)
        expected = {"key": "value", "more": "data"}
        self.assertEqual(expected, project1.extra_data)
        project1.refresh_from_db()
        self.assertEqual(expected, project1.extra_data)

    def test_scanpipe_codebase_resource_model_add_error(self):
        project1 = Project.objects.create(name="Analysis")
        codebase_resource = CodebaseResource.objects.create(project=project1)
        error = codebase_resource.add_error(Exception("Error message"))

        self.assertEqual(error, ProjectError.objects.get())
        self.assertEqual("CodebaseResource", error.model)
        self.assertTrue(error.details)
        self.assertEqual("Error message", error.message)
        self.assertEqual("", error.traceback)

    def test_scanpipe_codebase_resource_model_add_errors(self):
        project1 = Project.objects.create(name="Analysis")
        codebase_resource = CodebaseResource.objects.create(project=project1)
        codebase_resource.add_error(Exception("Error1"))
        codebase_resource.add_error(Exception("Error2"))
        self.assertEqual(2, ProjectError.objects.count())

    @skipIf(connection.vendor == "sqlite", "No max_length constraints on SQLite.")
    def test_scanpipe_project_error_model_save_non_valid_related_object(self):
        project1 = Project.objects.create(name="Analysis")
        long_value = "value" * 1000

        package = DiscoveredPackage.objects.create(
            project=project1, filename=long_value
        )
        # The DiscoveredPackage was not created
        self.assertIsNone(package.id)
        self.assertEqual(0, DiscoveredPackage.objects.count())
        # A ProjectError was saved instead
        self.assertEqual(1, project1.projecterrors.count())

        error = project1.projecterrors.get()
        self.assertEqual("DiscoveredPackage", error.model)
        self.assertEqual(long_value, error.details["filename"])
        self.assertEqual(
            "value too long for type character varying(255)\n", error.message
        )

        codebase_resource = CodebaseResource.objects.create(
            project=project1, type=long_value
        )
        self.assertIsNone(codebase_resource.id)
        self.assertEqual(0, CodebaseResource.objects.count())
        self.assertEqual(2, project1.projecterrors.count())

    @skipIf(connection.vendor == "sqlite", "No max_length constraints on SQLite.")
    def test_scanpipe_discovered_package_model_create_from_data(self):
        project1 = Project.objects.create(name="Analysis")

        package = DiscoveredPackage.create_from_data(project1, package_data1)
        self.assertEqual(project1, package.project)
        self.assertEqual("pkg:deb/debian/adduser@3.118?arch=all", str(package))
        self.assertEqual("deb", package.type)
        self.assertEqual("debian", package.namespace)
        self.assertEqual("adduser", package.name)
        self.assertEqual("3.118", package.version)
        self.assertEqual("arch=all", package.qualifiers)
        self.assertEqual("add and remove users and groups", package.description)
        self.assertEqual("849", package.size)
        self.assertEqual(
            "gpl-2.0 AND gpl-2.0-plus AND unknown", package.license_expression
        )

        package_count = DiscoveredPackage.objects.count()
        incomplete_data = dict(package_data1)
        incomplete_data["name"] = ""
        self.assertIsNone(DiscoveredPackage.create_from_data(project1, incomplete_data))
        self.assertEqual(package_count, DiscoveredPackage.objects.count())
        error = project1.projecterrors.latest("created_date")
        self.assertEqual("DiscoveredPackage", error.model)
        expected_message = (
            "One or more of the required fields have no value: type, name, version"
        )
        self.assertEqual(expected_message, error.message)
        self.assertEqual(package_data1["purl"], error.details["purl"])
        self.assertEqual("", error.details["name"])
        self.assertEqual("", error.traceback)

        package_count = DiscoveredPackage.objects.count()
        bad_data = dict(package_data1)
        bad_data["version"] = "a" * 200
        self.assertIsNone(DiscoveredPackage.create_from_data(project1, bad_data))
        self.assertEqual(package_count, DiscoveredPackage.objects.count())
        error = project1.projecterrors.latest("created_date")
        self.assertEqual("DiscoveredPackage", error.model)
        expected_message = "value too long for type character varying(100)\n"
        self.assertEqual(expected_message, error.message)
        self.assertEqual(bad_data["version"], error.details["version"])
        self.assertIn("in save", error.traceback)


class ScanPipeWalkTest(BaseScanPipeModelsTest, TestCase):
    data_location = Path(__file__).parent / "data"
    fixtures = [data_location / "asgiref-3.3.0_walk_test_fixtures.json"]

    def test_scanpipe_codebase_resource_walk(self):
        fixtures = [self.data_location / "asgiref-3.3.0_walk_test_fixtures.json"]
        project = Project.objects.create(name="asgiref_walk_test")
        project_asgiref = Project.objects.get(name="asgiref")
        asgiref_root = self.project_asgiref.codebaseresources.get(path="codebase")

        topdown_paths = list(r.path for r in asgiref_root.walk(topdown=True))
        expected_topdown_paths = [
            "codebase/asgiref-3.3.0.whl",
            "codebase/asgiref-3.3.0.whl-extract",
            "codebase/asgiref-3.3.0.whl-extract/asgiref",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/compatibility.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/current_thread_executor.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/__init__.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/local.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/server.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/sync.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/testing.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/timeout.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/wsgi.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/LICENSE",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/METADATA",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/RECORD",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/top_level.txt",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/WHEEL",
        ]
        self.assertEqual(expected_topdown_paths, topdown_paths)

        bottom_up_paths = list(r.path for r in asgiref_root.walk(topdown=False))
        expected_bottom_up_paths = [
            "codebase/asgiref-3.3.0.whl",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/compatibility.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/current_thread_executor.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/__init__.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/local.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/server.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/sync.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/testing.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/timeout.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref/wsgi.py",
            "codebase/asgiref-3.3.0.whl-extract/asgiref",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/LICENSE",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/METADATA",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/RECORD",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/top_level.txt",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info/WHEEL",
            "codebase/asgiref-3.3.0.whl-extract/asgiref-3.3.0.dist-info",
            "codebase/asgiref-3.3.0.whl-extract",
        ]
        self.assertEqual(expected_bottom_up_paths, bottom_up_paths)
