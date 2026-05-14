# BAU-FET Private Cloud Portal Backend

A Flask-based backend for the BAU-FET Private Cloud Portal, providing authentication, VM management, and request handling.

## Features

- User authentication with local user database
- Role-based access (Admin/User)
- VM request submission and management
- Proxmox API integration (placeholder)
- Session-based authentication

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Configure Proxmox settings in `app.py`:
   - Set `PROXMOX_HOST`, `PROXMOX_USER`, and `PROXMOX_TOKEN`

3. Run the application:
   ```
   python app.py
   ```

4. Open your browser to `http://localhost:5000`

## Usage

- Login with credentials from the USERS_DB (e.g., dr.ahmad/pass123)
- Submit VM requests via the form
- Admins can view all requests and VMs
- Users can only see their own

## API Endpoints

- `GET /`: Dashboard
- `POST /login`: Login
- `GET /logout`: Logout
- `POST /request_vm`: Submit VM request
- `GET /api/vms`: Get VMs (filtered by role)
- `GET /api/requests`: Get requests (filtered by role)
- `GET /api/users`: Get users (admin only)

## Data Storage

- Requests stored in `requests.json`
- VMs stored in `vms.json` (currently mock data)