def test_multipart_spool_max_size_in_memory() -> None:
    """Test that files smaller than spool_max_size stay in memory."""
    from starlette.formparsers import MultiPartParser, SpooledTemporaryFile
    from starlette.datastructures import Headers

    async def stream() -> bytes:
        yield (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            b"hello world\r\n"
            b"--boundary--\r\n"
        )

    headers = Headers({"content-type": "multipart/form-data; boundary=boundary"})
    parser = MultiPartParser(headers, stream(), spool_max_size=1024 * 1024)  # 1MB threshold
    result = parser.parse()
    import anyio

    data = anyio.run(result)

    file = data["file"]
    assert file.filename == "test.txt"
    assert file._in_memory is True  # Should still be in memory (small file)


def test_multipart_spool_max_size_rolled_to_disk() -> None:
    """Test that files larger than spool_max_size roll to disk."""
    from starlette.formparsers import MultiPartParser, SpooledTemporaryFile
    from starlette.datastructures import Headers

    async def stream() -> bytes:
        yield (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            + b"x" * (1024 * 1024 + 100)  # Slightly over 1MB
            + b"\r\n"
            b"--boundary--\r\n"
        )

    headers = Headers({"content-type": "multipart/form-data; boundary=boundary"})
    parser = MultiPartParser(headers, stream(), spool_max_size=1024 * 1024)  # 1MB threshold
    result = parser.parse()
    import anyio

    data = anyio.run(result)

    file = data["file"]
    assert file.filename == "test.txt"
    assert file._in_memory is False  # Should have rolled to disk


def test_multipart_custom_spool_max_size() -> None:
    """Test that custom spool_max_size parameter is respected."""
    from starlette.formparsers import MultiPartParser
    from starlette.datastructures import Headers

    async def stream() -> bytes:
        yield (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            b"x" * 500  # 500 bytes
            b"\r\n"
            b"--boundary--\r\n"
        )

    headers = Headers({"content-type": "multipart/form-data; boundary=boundary"})
    parser = MultiPartParser(headers, stream(), spool_max_size=100)  # Only 100 bytes threshold
    result = parser.parse()
    import anyio

    data = anyio.run(result)

    file = data["file"]
    assert file.filename == "test.txt"
    assert file._in_memory is False  # Should roll to disk (500 > 100)


def test_request_form_spool_max_size(test_client_factory: TestClientFactory) -> None:
    """Test that request.form() accepts spool_max_size parameter."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        # Set a very small spool_max_size to force disk usage
        form = await request.form(spool_max_size=100)
        file = form["file"]
        # Check if it rolled to disk
        rolled = not file._in_memory
        await request.close()
        response = JSONResponse({"rolled_to_disk": rolled, "filename": file.filename})
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.post("/", files={"file": ("test.txt", b"x" * 500)})
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "test.txt"
    assert data["rolled_to_disk"] is True  # Should roll with 100 byte threshold


def test_request_form_spool_max_size_default(test_client_factory: TestClientFactory) -> None:
    """Test that request.form() default spool_max_size keeps small files in memory."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        # Use default spool_max_size (1MB)
        form = await request.form()
        file = form["file"]
        in_memory = file._in_memory
        await request.close()
        response = JSONResponse({"in_memory": in_memory, "filename": file.filename})
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.post("/", files={"file": ("test.txt", b"x" * 500)})
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "test.txt"
    assert data["in_memory"] is True  # Should stay in memory with default threshold


def test_spool_max_size_zero_means_unlimited(test_client_factory: TestClientFactory) -> None:
    """Test that spool_max_size=0 means unlimited (stays in memory)."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        # Set spool_max_size to 0 (unlimited per SpooledTemporaryFile docs)
        form = await request.form(spool_max_size=0)
        file = form["file"]
        in_memory = file._in_memory
        await request.close()
        response = JSONResponse({"in_memory": in_memory})
        await response(scope, receive, send)

    client = test_client_factory(app)
    # Even a large file should stay in memory with spool_max_size=0
    response = client.post("/", files={"file": ("test.txt", b"x" * (1024 * 1024 * 5))})  # 5MB
    assert response.status_code == 200
    data = response.json()
    assert data["in_memory"] is True

