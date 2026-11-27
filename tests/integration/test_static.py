async def test_static_index(app_client):
    response = await app_client.get("/")
    assert response.status_code == 200
    assert "智能阅卷" in response.text


async def test_docs_still_available(app_client):
    assert (await app_client.get("/docs")).status_code == 200
