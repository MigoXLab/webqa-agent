import asyncio
import functools
import requests
import ssl
import socket
from datetime import datetime
from urllib.parse import urlparse
from webqa_agent.data.test_structures import SubTestResult, SubTestReport, TestStatus
import logging


class WebAccessibilityTest:
    async def run(self, url: str, sub_links: list) -> SubTestResult:
        logging.info(f"Starting combined HTTPS and status check for {url}")
        result = SubTestResult(name="可访问性检查")

        try:
            # check main link
            main_valid, main_reason, main_expiry_date = await self.check_https_expiry(url)
            main_status = await self.check_page_status(url)
            main_url_result = {
                "url": url,
                "status": main_status,
                "https_valid": main_valid,
                "https_reason": main_reason,
                "https_expiry_date": main_expiry_date
            }

            # check sub links
            sub_link_results = []
            failed_links = 0
            total_links = 1  # include main link

            if sub_links:
                total_links += len(sub_links)
                for link in sub_links:
                    sub_result = {"url": link, "status": None, "https_valid": None, "https_reason": None,
                                  "https_expiry_date": None}
                    try:
                        sub_result["https_valid"], sub_result["https_reason"], sub_result[
                            "https_expiry_date"] = await self.check_https_expiry(link)
                    except Exception as e:
                        logging.error(f"Failed to check HTTPS for {link}: {str(e)}")
                        sub_result["https"] = {"error": str(e)}
                    try:
                        sub_result["status"] = await self.check_page_status(link)
                    except Exception as e:
                        logging.error(f"Failed to check status for {link}: {str(e)}")
                        sub_result["status"] = {"error": str(e)}
                    sub_link_results.append(sub_result)

            # check if all passed
            def is_passed(item):
                https_valid = item["https_valid"]
                status_code = item["status"]
                # ensure status_code is an integer
                if isinstance(status_code, dict):
                    return False  # if status_code is a dict (contains error info), then test failed
                return https_valid and (status_code is not None and status_code < 400)

            all_passed = is_passed(main_url_result)
            if not all_passed:
                failed_links += 1

            if sub_links:
                for link in sub_link_results:
                    if not is_passed(link):
                        failed_links += 1
                all_passed = all_passed and all(is_passed(link) for link in sub_link_results)

            result.status = TestStatus.PASSED if all_passed else TestStatus.FAILED

            # add main link check steps
            result.report.append(
                SubTestReport(
                    title=f"主链接检查",
                    issues=f"测试结果: {main_url_result}"
                )
            )

            # add sub link check steps
            if sub_links:
                for i, sub_link_result in enumerate(sub_link_results):
                    result.report.append(
                        SubTestReport(
                            title=f"子链接检查 {i + 1}",
                            issues=f"测试结果: {sub_link_result}"
                        )
                    )


        except Exception as e:
            error_message = f"An error occurred in WebAccessibilityTest: {str(e)}"
            logging.error(error_message)
            result.status = TestStatus.FAILED
            result.messages = {"page": error_message}

        return result

    @staticmethod
    async def check_https_expiry(url: str, timeout: float = 10.0) -> tuple[bool, str, str]:
        """Check HTTPS certificate expiry in a thread to avoid blocking the event loop"""
        loop = asyncio.get_running_loop()

        def _sync_check():
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname
            port = 443
            result_valid = None
            result_reason = None
            result_expiry_date = None
            try:
                context = ssl.create_default_context()
                with socket.create_connection((hostname, port), timeout=timeout) as sock:
                    with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                        cert = ssock.getpeercert()

                expiry_date = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
                formatted_expiry_date = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
                result_valid = datetime.now() < expiry_date
                result_expiry_date = formatted_expiry_date
                logging.debug(f"HTTPS certificate is {'valid' if result_valid else 'expired'} for {url}")
            except ssl.SSLCertVerificationError as ssl_error:
                result_valid = False
                result_reason = ssl_error
                logging.error(f"SSL verification error: {ssl_error}")
            except Exception as e:
                result_valid = False
                result_reason = e
                logging.error(f"Error checking certificate: {str(e)}")
            return result_valid, result_reason, result_expiry_date

        return await loop.run_in_executor(None, _sync_check)

    @staticmethod
    async def check_page_status(url: str, timeout: float = 10.0) -> int:
        """Get page status code using requests in a thread pool to avoid blocking"""
        loop = asyncio.get_running_loop()

        def _sync_get():
            return requests.get(url, timeout=timeout)

        try:
            response = await loop.run_in_executor(None, _sync_get)
            status_code = response.status_code
            logging.info(f"Page {url} returned status {status_code}")
            return status_code
        except requests.RequestException as e:
            error_message = f"Failed to load page {url}: {str(e)}"
            logging.error(error_message)
            raise Exception(error_message)
