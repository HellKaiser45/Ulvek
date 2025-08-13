import os
import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from dataclasses import dataclass
from typing import List, Optional, Dict, Literal

DocumentState = Literal["initial", "finalized", "error", "delete"]


@dataclass
class SearchResult:
    id: str
    title: str
    description: str
    branch: str
    last_update_date: str
    state: DocumentState
    total_tokens: int
    total_snippets: int
    total_pages: int
    stars: Optional[int] = None
    trust_score: Optional[int] = None
    versions: Optional[List[str]] = None


@dataclass
class SearchResponse:
    results: List[SearchResult]
    error: Optional[str] = None


class AsyncContext7Client:
    def __init__(
        self,
        base_url: str = "https://context7.com/api",
        encryption_key: Optional[str] = None,
        default_type: str = "txt",
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_type = default_type
        self.timeout = timeout
        self.session = aiohttp.ClientSession(
            headers={"X-Context7-Source": "mcp-server"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        )

        self.encryption_key = encryption_key or os.getenv(
            "CLIENT_IP_ENCRYPTION_KEY", "0" * 64
        )
        self.valid_encryption_key = len(self.encryption_key) == 64 and all(
            c in "0123456789abcdefABCDEF" for c in self.encryption_key
        )

    # ---------- add these two methods ----------
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self) -> None:
        await self.session.close()

    def _encrypt_client_ip(self, client_ip: str) -> str:
        if not self.valid_encryption_key:
            return client_ip

        key_bytes = bytes.fromhex(self.encryption_key)
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()

        padded_data = padder.update(client_ip.encode()) + padder.finalize()
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return f"{iv.hex()}:{ciphertext.hex()}"

    async def _get_headers(self, client_ip: Optional[str]) -> Dict[str, str]:
        return (
            {"mcp-client-ip": self._encrypt_client_ip(client_ip)} if client_ip else {}
        )

    async def _handle_response(self, response: aiohttp.ClientResponse) -> dict:
        if response.status == 429:
            return {"error": "Rate limited due to too many requests"}
        return await response.json()

    async def search_libraries(
        self, query: str, client_ip: Optional[str] = None
    ) -> SearchResponse:
        url = f"{self.base_url}/v1/search"
        headers = await self._get_headers(client_ip)

        try:
            async with self.session.get(
                url, params={"query": query}, headers=headers
            ) as resp:
                data = await self._handle_response(resp)

                if "error" in data:
                    return SearchResponse([], data["error"])

                return SearchResponse(
                    [
                        SearchResult(
                            id=item["id"],
                            title=item["title"],
                            description=item["description"],
                            branch=item["branch"],
                            last_update_date=item["lastUpdateDate"],
                            state=item["state"],
                            total_tokens=item["totalTokens"],
                            total_snippets=item["totalSnippets"],
                            total_pages=item["totalPages"],
                            stars=item.get("stars"),
                            trust_score=item.get("trustScore"),
                            versions=item.get("versions"),
                        )
                        for item in data["results"]
                    ]
                )
        except Exception as e:
            return SearchResponse([], f"Request failed: {str(e)}")

    async def fetch_documentation(
        self,
        library_id: str,
        tokens: Optional[int] = None,
        topic: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Optional[str]:
        lib_id = library_id.lstrip("/")
        url = f"{self.base_url}/v1/{lib_id}"
        params = {"type": self.default_type}
        if tokens:
            params["tokens"] = str(tokens)
        if topic:
            params["topic"] = topic

        headers = await self._get_headers(client_ip)

        try:
            async with self.session.get(url, params=params, headers=headers) as resp:
                if resp.status == 429:
                    return "Rate limited due to too many requests"

                text = (await resp.text()).strip()
                return (
                    text
                    if text
                    and text
                    not in {"No content available", "No context data available"}
                    else None
                )

        except Exception as e:
            return f"Request failed: {str(e)}"

    async def search_and_fetch(
        self, query: str, client_ip: Optional[str] = None
    ) -> tuple[str, int, str]:
        """
        Search Context7 for a library and immediately fetch its documentation  .

        Parameters
        ----------
        query : str
            Free-text search term (e.g. "react", "pandas", "fastapi").
        client_ip : str | None, optional
            Client IP to forward for rate-limiting purposes; encrypted before
            transmission.

        Returns
        -------
        tuple[str, int, str]
            (documentation_text, total_tokens, library_title)
            • documentation_text : full documentation string for the best-matched
              library, or empty string if none found.
            • total_tokens       : token count reported by Context7 for the
              returned documentation.
            • library_title      : human-readable title of the matched library.

        Notes
        -----
        The function picks the first result among the top-3 search hits that has
        more than 100 GitHub stars.  If no such result exists, all three return
        values are empty/zero.
        """
        search_res = await self.search_libraries(query, client_ip)
        if search_res.error or not search_res.results:
            return "", 0, ""

        # Find first result with >100 stars in top 3
        for result in search_res.results[:3]:
            if result.stars and result.stars > 100:
                docs = await self.fetch_documentation(
                    result.id, result.total_tokens, client_ip=client_ip
                )
                return (docs or "", result.total_tokens, result.title)

        return "", 0, ""
