# scripts/ui_agent/ui_agent/utils/async_get_sso_token.py
import httpx
import json
import time
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
import base64
import copy
import tldextract
import asyncio
import requests
from typing import Tuple

sso_host = "https://sso.openxlab.org.cn"
puyu_host = "https://intern.openxlab.org.cn"
internlm_host = "https://internlm.intern-ai.org.cn/"


def rsa_encrpty(password, public_key):
    publicKey = (
        "-----BEGIN PUBLIC KEY-----\n" + public_key + "\n-----END PUBLIC KEY-----"
    )
    key = RSA.importKey(publicKey)
    cipher = PKCS1_v1_5.new(key)
    encrypt_text = base64.b64encode(cipher.encrypt(bytes(password.encode("utf8"))))
    return encrypt_text.decode("utf-8")


def extract_root_domain(url):
    # 使用tldextract提取URL的各个部分
    extracted = tldextract.extract(url)

    # 重新组合根域名，包括二级域名、顶级域名和公共后缀
    # 例如："subdomain.domain.tld"
    root_domain = f".{extracted.domain}.{extracted.suffix}"

    return root_domain


async def get_sso_token(username: str = "ui_test@pjlab.org.cn", password: str = "Test0315") -> Tuple[str, str]:
        async with httpx.AsyncClient() as client:
            res_rsa = await client.post(sso_host + "/gw/uaa-be/api/v1/cipher/getPubKey",
                                        json={
                                            "type": "login",
                                            "from": "browser",
                                            "clientId": "",
                                        },
                                        headers={
                                            "Connection": "keep-alive",
                                            "Accept": "application/json, text/plain, */*",
                                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
                                            "Content-Type": "application/json;charset=UTF-8"
                                        })
            if res_rsa.status_code != 200:
                raise Exception(f"sso getPubKey failed, status_code:{res_rsa.status_code},res.content:{res_rsa.content}")

            key = res_rsa.json().get("data").get("pubKey")
            timestamp = str(int(time.time()))
            loginByAccount = {
                "account": username,
                "password": password,
                "autoLogin": "true"
            }
            encrpty_password = rsa_encrpty(
                loginByAccount.get("account") + "||" + loginByAccount.get("password") + "||" +
                timestamp, key)
            loginBySdk_data = copy.copy(loginByAccount)
            loginBySdk_data.update({"password": encrpty_password})

            res_login = await client.post(sso_host + "/gw/uaa-be/api/v1/login/byAccount",
                                        headers={
                                            "Connection": "keep-alive",
                                            "Accept": "application/json, text/plain, */*",
                                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
                                            "Content-Type": "application/json;charset=UTF-8"
                                        },
                                        json=loginBySdk_data)
            if res_login.status_code != 200 or res_login.json().get("msgCode") != '10000':
                raise Exception(f"sso byClientSdk failed, status_code:{res_login.status_code},res.content:{res_login.content}")

            token = res_login.headers.get("authorization")
        
            
            # Generate cookies
            cookie_list = []
            domain = extract_root_domain(puyu_host)
            
            token = res_login.headers.get("authorization")
            if not token:
                raise Exception("SSO login failed: No authorization token received in response headers")
            
            cookies = res_login.cookies
            if not cookies:
                raise Exception("SSO login failed: No cookies received in response")
            
            # Process cookies
            for cookie_name, cookie_value in cookies.items():
                cookie_info = {
                    "name": cookie_name,
                    "value": cookie_value,
                    "domain": ".openxlab.org.cn",
                    "path": "/",
                }
                cookie_list.append(cookie_info)
                
                cookie_info_intern = {
                    "name": cookie_name,
                    "value": cookie_value,
                    "domain": ".intern-ai.org.cn",
                    "path": "/",
                }
                cookie_info_mineru = {
                    "name": cookie_name,
                    "value": cookie_value,
                    "domain": ".mineru.net",
                    "path": "/",
                }
                cookie_list.append(cookie_info_intern)
                cookie_list.append(cookie_info_mineru)
            
            cookie_json = json.dumps(cookie_list)
            return token, cookie_json

def get_sso_token_sync(username: str = "ui_test@pjlab.org.cn", password: str = "Test0315") -> Tuple[str, str]:
    # Get user's encrypted password
    try:
        res_rsa = requests.post(
            sso_host + "/gw/uaa-be/api/v1/cipher/getPubKey",
            data=json.dumps(
                {
                    "type": "login",
                    "from": "browser",
                    "clientId": "",
                }
            ),
            headers={
                "Connection": "keep-alive",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
                "Content-Type": "application/json;charset=UTF-8",
            },
            verify=False,
            timeout=30,  # Add timeout
        )
        
        if res_rsa.status_code != 200:
            raise Exception(
                f"SSO login failed: Unable to get pubKey. Status code: {res_rsa.status_code}, Response: {res_rsa.content}"
            )
            
        # Check if the response has the expected structure
        pubkey_data = res_rsa.json().get("data")
        if not pubkey_data or not pubkey_data.get("pubKey"):
            raise Exception(f"SSO login failed: Invalid pubKey response format. Response: {res_rsa.content}")
        
        key = pubkey_data.get("pubKey")
    except requests.RequestException as e:
        raise Exception(f"SSO login failed: Connection error while getting pubKey: {str(e)}")
    except json.JSONDecodeError:
        raise Exception(f"SSO login failed: Invalid JSON response when getting pubKey: {res_rsa.content}")
    except Exception as e:
        raise Exception(f"SSO login failed: Unexpected error when getting pubKey: {str(e)}")

    # Update login parameters
    try:
        timestamp = str(int(time.time()))
        loginBySdk = {
            "account": username,
            "password": password,
            "autoLogin": "true",
        }
        encrpty_password = rsa_encrpty(
            loginBySdk.get("account")
            + "||"
            + loginBySdk.get("password")
            + "||"
            + timestamp,
            key,
        )
        loginBySdk_data = copy.copy(loginBySdk)
        loginBySdk_data.update({"password": encrpty_password})

        # Attempt login
        res_login = requests.post(
            sso_host + "/gw/uaa-be/api/v1/login/byClientSdk",
            headers={
                "Connection": "keep-alive",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
                "Content-Type": "application/json;charset=UTF-8",
            },
            data=json.dumps(loginBySdk_data),
            verify=False,
            timeout=30,  # Add timeout
        )
        
        # Enhanced error handling for login
        if res_login.status_code != 200:
            raise Exception(
                f"SSO login failed: Invalid status code: {res_login.status_code}, Response: {res_login.content}"
            )
            
        response_json = res_login.json()
        if response_json.get("msgCode") != "10000":
            error_msg = response_json.get("msg", "Unknown error")
            error_code = response_json.get("msgCode", "Unknown code")
            raise Exception(
                f"SSO login failed: Authentication error (code: {error_code}): {error_msg}"
            )
    except requests.RequestException as e:
        raise Exception(f"SSO login failed: Connection error during authentication: {str(e)}")
    except json.JSONDecodeError:
        raise Exception(f"SSO login failed: Invalid JSON response during authentication: {res_login.content}")
    except Exception as e:
        raise Exception(f"SSO login failed: Unexpected error during authentication: {str(e)}")

    # Generate cookies (keeping this part unchanged)
    cookie_list = []
    try:
        token = res_login.headers.get("authorization")
        if not token:
            raise Exception("SSO login failed: No authorization token received in response headers")
            
        cookies = res_login.cookies.items()
        if not cookies:
            raise Exception("SSO login failed: No cookies received in response")
            
        # The cookie generation logic remains unchanged
        for name, value in cookies:
            cookie_info = {
                "name": name,
                "value": value,
                "domain": ".openxlab.org.cn",
                "path": "/",
            }
            cookie_list.append(cookie_info)

        for name, value in cookies:
            cookie_info_intern = {
                "name": name,
                "value": value,
                "domain": ".intern-ai.org.cn",
                "path": "/",
            }
            cookie_list.append(cookie_info_intern)
        
        for name, value in cookies:
            cookie_info_mineru = {
                "name": name,
                "value": value,
                "domain": ".mineru.net",
                "path": "/",
            }
            cookie_list.append(cookie_info_mineru)

        cookie_json = json.dumps(cookie_list)
        return token, cookie_json
    except Exception as e:
        raise Exception(f"SSO login failed: Unable to process authentication cookies: {str(e)}")
