##########################################
# Basic App Test
##########################################

from app.main import main
from dotenv import load_dotenv

load_dotenv()


def test_main():
    main()

##########################################
# FastAPI App Test
##########################################

# from fastapi.testclient import TestClient
# from app.main import app
# from dotenv import load_dotenv

# load_dotenv()

# client = TestClient(app)


# def test_ping():
#     response = client.get("/ping")
#     assert response.status_code == 200
#     assert response.json() == {"message": "pong"}
