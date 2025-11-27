"""Case result saver for crash-safe test execution.

This module provides functionality to save case results immediately after execution
to prevent data loss in case of interruptions (crashes, KeyboardInterrupt, etc.).
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from webqa_agent.data import TestResult, TestStatus


class CaseResultSaver:
    """Saves case results immediately after execution to prevent data loss on interruption.

    Architecture:
    - Each case result is saved to individual JSON file immediately after case completion
    - Manifest file tracks overall session state and case file list
    - Atomic writes using temporary files + rename for crash safety
    - Async I/O to avoid blocking test execution

    Directory Structure:
        reports/test_{timestamp}/
        └── case_results/
            ├── case_01.json
            ├── case_02.json
            ├── .manifest.json
            └── .lock
    """

    VERSION = "1.0"

    def __init__(self, report_dir: str):
        """Initialize case result saver.

        Args:
            report_dir: Root report directory (e.g., './reports/test_20251118_103000')
        """
        self.report_dir = Path(report_dir)
        self.case_results_dir = self.report_dir / "case_results"
        self.manifest_path = self.case_results_dir / ".manifest.json"

        # Async lock for thread-safe file operations
        self._lock = asyncio.Lock()  # avoid multi-cases to write content at the same time

        # In-memory manifest cache
        self._manifest: Optional[Dict[str, Any]] = None

        # Counter for test file numbering
        self._test_counter = 0

        logging.debug(f"CaseResultSaver initialized: {self.case_results_dir}")

    async def initialize(self, session_id: str, total_tests: int):
        """Initialize case results save directory and manifest.

        Args:
            session_id: Unique session identifier
            total_tests: Total number of tests planned for execution
        """
        async with self._lock:
            try:
                # Create case results directory
                self.case_results_dir.mkdir(parents=True, exist_ok=True)

                # Initialize manifest
                self._manifest = {
                    "version": self.VERSION,
                    "session_id": session_id,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "total_tests": total_tests,
                    "completed_tests": 0,
                    "status": "in_progress",
                    "test_files": []
                }

                # Save initial manifest
                await self._write_manifest()

                logging.info(
                    f"Case result saver initialized: session_id={session_id}, "
                    f"total_tests={total_tests}, dir={self.case_results_dir}"
                )

            except Exception as e:
                logging.error(f"Failed to initialize case result saver: {e}", exc_info=True)
                # Non-fatal: execution can continue without case result saves

    async def save_test_result(self, test_result: TestResult):
        """Save individual test result atomically.

        This method:
        1. Serializes TestResult to JSON
        2. Writes to temporary file
        3. Atomically renames to final location
        4. Updates manifest

        Args:
            test_result: Test result to save
        """
        if not self._manifest:
            logging.warning("Case result saver not initialized, skipping save")
            return

        async with self._lock:
            try:
                # Generate unique filename
                self._test_counter += 1
                test_filename = f"test_{test_result.test_id}_{self._test_counter:03d}.json"
                test_filepath = self.case_results_dir / test_filename
                temp_filepath = self.case_results_dir / f".{test_filename}.tmp"

                # Serialize test result
                test_data = {
                    "version": self.VERSION,
                    "saved_at": datetime.now().isoformat(),
                    "test_result": test_result.dict()
                }

                # Atomic write: temp file + rename
                await self._write_json_atomic(temp_filepath, test_filepath, test_data)

                # Update manifest
                self._manifest["test_files"].append({
                    "test_id": test_result.test_id,
                    "test_name": test_result.test_name,
                    "file": test_filename,
                    "status": test_result.status.value,
                    "saved_at": test_data["saved_at"]
                })
                self._manifest["completed_tests"] = len(self._manifest["test_files"])
                self._manifest["updated_at"] = datetime.now().isoformat()

                await self._write_manifest()

                logging.info(
                    f"Incremental save: {test_result.test_name} ({test_result.status.value}) "
                    f"-> {test_filename}"
                )

            except Exception as e:
                logging.error(
                    f"Failed to save test result incrementally (test_id={test_result.test_id}): {e}",
                    exc_info=True
                )
                # Non-fatal: test execution continues

    async def save_case_result(self, case_number: int, case_name: str, status: str):
        """Save case result metadata to manifest.

        This method updates the manifest's test_files list and completed_tests counter
        after a case file has been saved.

        Args:
            case_number: Case number (e.g., 1 for case_01.json)
            case_name: Case name
            status: Case status ('passed', 'failed', 'cancelled', 'warning')
        """
        if not self._manifest:
            logging.warning("Case result saver not initialized, skipping manifest update")
            return

        async with self._lock:
            try:
                case_filename = f"case_{case_number:02d}.json"

                # Add to test_files list (avoid duplicates)
                existing_files = [f["file"] for f in self._manifest["test_files"]]
                if case_filename not in existing_files:
                    self._manifest["test_files"].append({
                        "file": case_filename,
                        "case_name": case_name,
                        "case_number": case_number,
                        "status": status,
                        "saved_at": datetime.now().isoformat()
                    })

                    # Update completed count
                    self._manifest["completed_tests"] = len(self._manifest["test_files"])
                    self._manifest["updated_at"] = datetime.now().isoformat()

                    await self._write_manifest()

                    logging.debug(
                        f"Updated manifest: {case_filename} (status={status}), "
                        f"completed={self._manifest['completed_tests']}/{self._manifest['total_tests']}"
                    )

            except Exception as e:
                logging.error(f"Failed to update manifest for {case_name}: {e}", exc_info=True)

    async def finalize(self, status: str):
        """Mark session as completed/cancelled/failed.

        Args:
            status: Final session status ('completed', 'cancelled', 'failed')
        """
        if not self._manifest:
            logging.warning("Case result saver not initialized, skipping finalize")
            return

        async with self._lock:
            try:
                self._manifest["status"] = status
                self._manifest["updated_at"] = datetime.now().isoformat()

                await self._write_manifest()

                logging.info(
                    f"Case result saver finalized: status={status}, "
                    f"completed_tests={self._manifest['completed_tests']}/{self._manifest['total_tests']}"
                )

            except Exception as e:
                logging.error(f"Failed to finalize incremental saver: {e}", exc_info=True)

    async def recover_partial_results(self) -> List[TestResult]:
        """Recover test results from interrupted session.

        Returns:
            List of recovered TestResult objects
        """
        async with self._lock:
            try:
                if not self.manifest_path.exists():
                    logging.warning(f"No manifest found at {self.manifest_path}")
                    return []

                # Read manifest
                with open(self.manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)

                # Recover test results from individual files
                recovered_results = []
                for test_file_entry in manifest.get("test_files", []):
                    test_filename = test_file_entry["file"]
                    test_filepath = self.case_results_dir / test_filename

                    if not test_filepath.exists():
                        logging.warning(f"Test file missing: {test_filepath}")
                        continue

                    try:
                        with open(test_filepath, 'r', encoding='utf-8') as f:
                            test_data = json.load(f)

                        # Reconstruct TestResult from dict
                        test_result_dict = test_data["test_result"]
                        test_result = TestResult(**test_result_dict)
                        recovered_results.append(test_result)

                    except Exception as e:
                        logging.error(f"Failed to recover test result from {test_filename}: {e}")
                        continue

                logging.info(
                    f"Recovered {len(recovered_results)} test results from incremental saves "
                    f"(session_id={manifest.get('session_id')})"
                )

                return recovered_results

            except Exception as e:
                logging.error(f"Failed to recover partial results: {e}", exc_info=True)
                return []

    async def get_manifest(self) -> Optional[Dict[str, Any]]:
        """Get current manifest data.

        Returns:
            Manifest dictionary or None if not initialized
        """
        async with self._lock:
            return dict(self._manifest) if self._manifest else None

    async def save_in_progress_case(self, test_id: str, test_name: str, case_data: dict):
        """Save in-progress case data (with steps) to incremental file.

        This method is called after each step completes via CentralCaseRecorder callback.
        It saves the current state of a test case that is still executing.

        Args:
            test_id: Test identifier
            test_name: Test name
            case_data: Current case data from CentralCaseRecorder.get_case_data()
        """
        if not self._manifest:
            logging.warning("Case result saver not initialized, skipping in-progress save")
            return

        async with self._lock:
            try:
                # Generate in-progress filename
                in_progress_file = f".test_{test_id}_in_progress.json"
                in_progress_path = self.case_results_dir / in_progress_file
                temp_path = self.case_results_dir / f".{in_progress_file}.tmp"

                # Build in-progress data
                in_progress_data = {
                    "version": self.VERSION,
                    "test_id": test_id,
                    "test_name": test_name,
                    "case_name": case_data.get("name", ""),
                    "status": case_data.get("status", "in_progress"),
                    "start_time": case_data.get("start_time"),
                    "last_updated": datetime.now().isoformat(),
                    "total_steps_planned": None,  # Unknown until case completes
                    "completed_steps": len(case_data.get("steps", [])),
                    "steps": case_data.get("steps", []),
                    "final_summary": case_data.get("final_summary", "")
                }

                # Atomic write
                await self._write_json_atomic(temp_path, in_progress_path, in_progress_data)

                logging.debug(
                    f"In-progress save: {test_id}/{case_data.get('name')} "
                    f"(steps: {in_progress_data['completed_steps']})"
                )

            except Exception as e:
                logging.error(
                    f"Failed to save in-progress case (test_id={test_id}): {e}",
                    exc_info=True
                )
                # Non-fatal: execution continues

    async def finalize_in_progress_case(self, test_id: str):
        """Clean up in-progress file when case completes.

        Args:
            test_id: Test identifier
        """
        async with self._lock:
            try:
                in_progress_file = self.case_results_dir / f".test_{test_id}_in_progress.json"

                if not in_progress_file.exists():
                    logging.debug(f"No in-progress file found for {test_id} (already cleaned or never created)")
                    return

                # Delete in-progress file since complete result is saved
                in_progress_file.unlink()

                logging.debug(f"Cleaned up in-progress file for {test_id}")

            except Exception as e:
                logging.error(f"Failed to finalize in-progress case: {e}", exc_info=True)

    # =========================================================================
    # Private Helper Methods
    # =========================================================================

    async def _write_manifest(self):
        """Write manifest file atomically."""
        temp_path = self.case_results_dir / ".manifest.json.tmp"
        final_path = self.manifest_path

        await self._write_json_atomic(temp_path, final_path, self._manifest)

    async def _write_json_atomic(
        self,
        temp_path: Path,
        final_path: Path,
        data: Dict[str, Any]
    ):
        """Write JSON file atomically using temp file + rename.

        This ensures crash safety: file is either fully written or not written at all.

        Args:
            temp_path: Temporary file path
            final_path: Final file path
            data: Data to serialize
        """
        try:
            # Write to temporary file
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._write_json_sync,
                temp_path,
                data
            )

            # Atomic rename (POSIX guarantees atomicity)
            await loop.run_in_executor(None, os.replace, str(temp_path), str(final_path))

        except Exception as e:
            # Clean up temp file on failure
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise e

    @staticmethod
    def _write_json_sync(filepath: Path, data: Dict[str, Any]):
        """Synchronous JSON write helper."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# =============================================================================
# Recovery Utilities
# =============================================================================

async def list_case_result_sessions(reports_dir: str = "./reports") -> List[Dict[str, Any]]:
    """List all sessions with case result saves.

    Args:
        reports_dir: Root reports directory

    Returns:
        List of session metadata dictionaries
    """
    reports_path = Path(reports_dir)
    sessions = []

    if not reports_path.exists():
        return sessions

    for report_subdir in reports_path.iterdir():
        if not report_subdir.is_dir():
            continue

        case_results_dir = report_subdir / "case_results"
        manifest_path = case_results_dir / ".manifest.json"

        if manifest_path.exists():
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)

                sessions.append({
                    "report_dir": str(report_subdir),
                    "session_id": manifest.get("session_id"),
                    "status": manifest.get("status"),
                    "total_tests": manifest.get("total_tests"),
                    "completed_tests": manifest.get("completed_tests"),
                    "created_at": manifest.get("created_at"),
                    "updated_at": manifest.get("updated_at")
                })
            except Exception as e:
                logging.warning(f"Failed to read manifest from {manifest_path}: {e}")
                continue

    return sessions


async def recover_session(report_dir: str) -> List[TestResult]:
    """Recover test results from a specific session directory.

    Args:
        report_dir: Path to report directory containing case result saves

    Returns:
        List of recovered TestResult objects
    """
    saver = CaseResultSaver(report_dir)
    return await saver.recover_partial_results()


async def recover_in_progress_cases(report_dir: str) -> List[Dict[str, Any]]:
    """Recover in-progress cases from a specific session directory.

    Args:
        report_dir: Path to report directory containing case result saves

    Returns:
        List of in-progress case data dictionaries
    """
    case_results_dir = Path(report_dir) / "case_results"
    if not case_results_dir.exists():
        return []

    in_progress_cases = []

    for filepath in case_results_dir.glob(".test_*_in_progress.json"):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                case_data = json.load(f)
            in_progress_cases.append(case_data)
        except Exception as e:
            logging.warning(f"Failed to recover in-progress case from {filepath}: {e}")
            continue

    logging.info(f"Recovered {len(in_progress_cases)} in-progress cases from {report_dir}")
    return in_progress_cases