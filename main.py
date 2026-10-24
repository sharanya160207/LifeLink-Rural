
from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = Path(__file__).with_name("ruraltresq.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS donors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                blood_group TEXT NOT NULL,
                village TEXT NOT NULL,
                phone TEXT NOT NULL,
                available INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS ambulances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                village TEXT NOT NULL,
                phone TEXT NOT NULL,
                available INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_type TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                village TEXT NOT NULL,
                blood_group TEXT,
                details TEXT,
                status TEXT NOT NULL DEFAULT 'Pending'
            );
        """)

        # Add sample records only when the tables are empty.
        if db.execute("SELECT COUNT(*) FROM donors").fetchone()[0] == 0:
            db.executemany(
                """INSERT INTO donors
                   (name, blood_group, village, phone, available)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    ("Demo Donor One", "O+", "Bantwal", "9000000001", 1),
                    ("Demo Donor Two", "B+", "Mangaluru", "9000000002", 1),
                    ("Demo Donor Three", "A+", "Puttur", "9000000003", 1),
                ],
            )

        if db.execute("SELECT COUNT(*) FROM ambulances").fetchone()[0] == 0:
            db.executemany(
                """INSERT INTO ambulances
                   (provider, village, phone, available)
                   VALUES (?, ?, ?, ?)""",
                [
                    ("Demo Rural Ambulance", "Bantwal", "9000000011", 1),
                    ("Demo Emergency Transport", "Puttur", "9000000012", 1),
                ],
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="RuralResQ API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


class DonorInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    blood_group: str
    village: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=7, max_length=20)


class AmbulanceInput(BaseModel):
    provider: str = Field(min_length=2, max_length=100)
    village: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=7, max_length=20)


class RequestInput(BaseModel):
    request_type: str
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=7, max_length=20)
    village: str = Field(min_length=2, max_length=100)
    blood_group: str | None = None
    details: str | None = Field(default=None, max_length=1000)


class AvailabilityInput(BaseModel):
    available: bool


BLOOD_GROUPS = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}


@app.get("/")
def home():
    return {"message": "Welcome to RuralResQ", "status": "running"}


@app.get("/api/stats")
def get_stats():
    with get_db() as db:
        return {
            "donors": db.execute(
                "SELECT COUNT(*) FROM donors"
            ).fetchone()[0],
            "available_donors": db.execute(
                "SELECT COUNT(*) FROM donors WHERE available=1"
            ).fetchone()[0],
            "ambulances": db.execute(
                "SELECT COUNT(*) FROM ambulances"
            ).fetchone()[0],
            "pending_requests": db.execute(
                "SELECT COUNT(*) FROM requests WHERE status='Pending'"
            ).fetchone()[0],
        }


@app.get("/api/donors")
def list_donors(
    blood_group: str | None = None,
    village: str | None = None,
):
    sql = "SELECT * FROM donors WHERE 1=1"
    params = []

    if blood_group:
        group = blood_group.strip().upper()
        if group not in BLOOD_GROUPS:
            raise HTTPException(400, "Invalid blood group")
        sql += " AND blood_group=?"
        params.append(group)

    if village and village.strip():
        sql += " AND village LIKE ?"
        params.append(f"%{village.strip()}%")

    with get_db() as db:
        return [dict(row) for row in db.execute(
            sql + " ORDER BY name", params
        ).fetchall()]


@app.post("/api/donors", status_code=201)
def add_donor(data: DonorInput):
    group = data.blood_group.strip().upper()
    if group not in BLOOD_GROUPS:
        raise HTTPException(400, "Invalid blood group")

    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO donors
               (name, blood_group, village, phone)
               VALUES (?, ?, ?, ?)""",
            (data.name.strip(), group, data.village.strip(), data.phone.strip()),
        )
        return {"id": cursor.lastrowid, "message": "Donor registered"}


@app.get("/api/ambulances")
def list_ambulances(village: str | None = None):
    sql = "SELECT * FROM ambulances"
    params = []

    if village and village.strip():
        sql += " WHERE village LIKE ?"
        params.append(f"%{village.strip()}%")

    with get_db() as db:
        return [dict(row) for row in db.execute(
            sql + " ORDER BY provider", params
        ).fetchall()]


@app.post("/api/ambulances", status_code=201)
def add_ambulance(data: AmbulanceInput):
    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO ambulances (provider, village, phone)
               VALUES (?, ?, ?)""",
            (data.provider.strip(), data.village.strip(), data.phone.strip()),
        )
        return {"id": cursor.lastrowid, "message": "Ambulance registered"}


@app.patch("/api/donors/{donor_id}/availability")
def donor_availability(donor_id: int, data: AvailabilityInput):
    with get_db() as db:
        cursor = db.execute(
            "UPDATE donors SET available=? WHERE id=?",
            (int(data.available), donor_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Donor not found")
    return {"message": "Availability updated"}


@app.patch("/api/ambulances/{ambulance_id}/availability")
def ambulance_availability(ambulance_id: int, data: AvailabilityInput):
    with get_db() as db:
        cursor = db.execute(
            "UPDATE ambulances SET available=? WHERE id=?",
            (int(data.available), ambulance_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Ambulance not found")
    return {"message": "Availability updated"}


@app.post("/api/requests", status_code=201)
def create_request(data: RequestInput):
    request_type = data.request_type.strip().lower()
    if request_type not in {"ambulance", "blood"}:
        raise HTTPException(400, "Type must be ambulance or blood")

    if request_type == "blood":
        group = (data.blood_group or "").strip().upper()
        if group not in BLOOD_GROUPS:
            raise HTTPException(400, "A valid blood group is required")
    else:
        group = None

    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO requests
               (request_type, name, phone, village, blood_group, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                request_type,
                data.name.strip(),
                data.phone.strip(),
                data.village.strip(),
                group,
                (data.details or "").strip(),
            ),
        )
        return {
            "id": cursor.lastrowid,
            "message": "Emergency request submitted",
            "status": "Pending",
        }


@app.get("/api/requests")
def list_requests(status: str | None = Query(default=None)):
    sql = "SELECT * FROM requests"
    params = []

    if status:
        sql += " WHERE status=?"
        params.append(status)

    with get_db() as db:
        return [dict(row) for row in db.execute(
            sql + " ORDER BY id DESC", params
        ).fetchall()]


@app.patch("/api/requests/{request_id}/status")
def update_request_status(request_id: int, status: str):
    if status not in {"Pending", "In Progress", "Resolved"}:
        raise HTTPException(400, "Invalid status")

    with get_db() as db:
        cursor = db.execute(
            "UPDATE requests SET status=? WHERE id=?",
            (status, request_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Request not found")

    return {"message": "Request status updated"}
