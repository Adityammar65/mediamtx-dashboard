# JWT Authentication Setup

## Overview

This document provides instructions for setting up JWT (JSON Web Token) authentication for the MediaMTX Dashboard. The authentication system provides a secure way to protect access to the dashboard API endpoints.

## Prerequisites

- Python 3.7 or higher
- FastAPI and related dependencies (should be installed via `requirements.txt`)
- `PyJWT` library (included in `requirements.txt`)

## Configuration

### 1. Environment Variables

Create or update a `.env` file in the project root directory with the following environment variables:

```env
AUTH_USERNAME=admin
AUTH_PASSWORD=admin
JWT_SECRET=YOUR_STRONG_RANDOM_SECRET_HERE
JWT_EXPIRE_MINUTES=480
JWT_SECURE_COOKIE=false
```

#### Explanation of Environment Variables:

- **`AUTH_USERNAME`**: Username for the admin account (default: "admin")
- **`AUTH_PASSWORD`**: Password for the admin account (default: "admin")
- **`JWT_SECRET`**: Secret key used to sign JWT tokens. **This must be a strong, randomly generated string for production**. The secret should be at least 32 characters long and contain a mix of uppercase letters, lowercase letters, numbers, and special characters.
- **`JWT_EXPIRE_MINUTES`**: Token expiration time in minutes (default: 480 minutes = 8 hours)
- **`JWT_SECURE_COOKIE`**: Whether to set the `Secure` flag on cookies (default: false). Set to `true` for HTTPS deployments.

### 2. Generating a JWT Secret

For production, you should generate a strong random secret:

```bash
# Option 1: Use Python
s python -c "import secrets; print(secrets.token_urlsafe(32))"

# Option 2: Use a secure random string generator
# Visit https://www.securegeneratepassword.com/ or similar service
```

**Important**: Keep this secret secure and never commit it to version control!

### 3. `.env.example` File

A template `.env.example` file is included in the project root to guide setup. It contains all the required and optional environment variables with explanations.

## Usage

### 1. Starting the Application

```bash
# Install dependencies (if not already installed)
pip install -r requirements.txt

# Start the application
python app.py
```

Or using Docker:

```bash
# Build and run the Docker container
docker-compose build
docker-compose up
```

### 2. First-Time Login

1. Open your web browser and navigate to the dashboard URL (e.g., `http://localhost:8000`)
2. You will be automatically redirected to the login page
3. Enter the credentials (default: `admin:admin` unless configured differently)
4. After successful login, you will be redirected to the dashboard

### 3. Accessing the Application

- **After successful login**: All dashboard pages and API endpoints will be accessible
- **After logout**: You will be redirected to the login page when trying to access any dashboard page
- **Invalid credentials**: The login form will display an error message

### 4. Session Management

- **Session Timeout**: Tokens automatically expire after the configured time (default: 8 hours)
- **Logout**: Click the logout button in the dashboard to clear the session
- **Browser Close**: Sessions are cleared when the browser is closed

## Security Considerations

### 1. Password Security

- Use strong passwords for `AUTH_PASSWORD`
- Consider implementing password complexity requirements in production
- Never share credentials through insecure channels

### 2. JWT Secret Security

- **Never** commit the JWT secret to version control
- Use a secrets management system in production (e.g., AWS Secrets Manager, HashiCorp Vault)
- Rotate the JWT secret periodically (recommended every 90 days)
- Use different secrets for different environments (development, staging, production)

### 3. Cookie Security

- The JWT token is stored in an `HttpOnly` cookie, which prevents client-side JavaScript access
- Set `JWT_SECURE_COOKIE=true` for HTTPS deployments
- Consider using additional security headers (HSTS, CSP, etc.)

### 4. Authentication Protection

- All API endpoints require authentication except the `/api/login` endpoint
- Invalid, expired, or missing tokens result in a 401 Unauthorized error
- The frontend automatically redirects to the login page when authentication fails

## Frontend Login Experience

### 1. Login Page

- The login page is displayed when the user first visits the dashboard or after logout
- It features a clean, responsive design
- Includes visual feedback for invalid login attempts
- Displays information about default credentials and configuration

### 2. Dashboard Access

- After successful login, the user is redirected to the dashboard
- Navigation links are highlighted to indicate the current page
- Connection status is displayed in the header
- A refresh button is available to reload data

### 3. Session Persistence

- Login state is maintained across page navigations
- Tokens are automatically sent with API requests via cookies
- Users can manually logout using the logout button

## Testing

### 1. Unit Tests

The application includes unit tests for authentication functionality. Run the tests:

```bash
pytest
```

### 2. Manual Testing

#### Testing Login Functionality:

1. **Valid Credentials**:
   - Enter correct `AUTH_USERNAME` and `AUTH_PASSWORD`
   - Verify successful login and redirect to dashboard

2. **Invalid Credentials**:
   - Enter incorrect username or password
   - Verify error message is displayed
   - Verify user remains on login page

3. **Empty Fields**:
   - Leave username or password fields empty
   - Verify validation prevents login

4. **Token Validation**:
   - Test that protected API endpoints require authentication
   - Verify that invalid/expired tokens are rejected
   - Confirm that valid tokens grant access

5. **Cookie Attributes**:
   - Verify that the JWT cookie has `HttpOnly` and `SameSite=Lax` attributes
   - If `JWT_SECURE_COOKIE=true`, verify the `Secure` flag is set

### 3. API Testing

Use tools like Postman or curl to test API endpoints:

```bash
# Test login endpoint
curl -X POST http://localhost:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'

# Test protected endpoint with token
curl -X GET http://localhost:8000/api/server/health \
  -H "Cookie: access_token=YOUR_JWT_TOKEN_HERE"
```

## Troubleshooting

### Common Issues and Solutions

#### Issue: "Invalid credentials" message

**Cause**: Incorrect username or password
**Solution**: Verify the `AUTH_USERNAME` and `AUTH_PASSWORD` environment variables

#### Issue: Application cannot start (JWT_SECRET not configured)

**Cause**: Empty or missing JWT_SECRET
**Solution**: Generate a strong JWT secret and update the `.env` file

#### Issue: Token expired

**Cause**: Token has exceeded the configured expiration time
**Solution**: User needs to login again

#### Issue: Application running on HTTP but JWT_SECURE_COOKIE=true

**Cause**: Insecure configuration
**Solution**: Set `JWT_SECURE_COOKIE=false` or use HTTPS

## Migration

### From No Authentication to JWT Authentication

1. **Backup Configuration**: Ensure you have a backup of your current `.env` file
2. **Add Environment Variables**: Add the JWT authentication variables to your `.env` file
3. **Generate JWT Secret**: Create a strong random secret
4. **Test**: Test the application with the new authentication
5. **Update User Credentials**: Update any user documentation to reflect the new authentication
6. **Deploy**: Deploy the updated application

### From Existing Authentication to JWT

If you already have a custom authentication system, you can migrate to JWT by:

1. **Review Configuration**: Review your current authentication setup
2. **Plan Migration**: Plan the migration approach (gradual vs. direct switch)
3. **Update Code**: Update the application code to use JWT
4. **Test**: Thoroughly test the migration
5. **Rollback Plan**: Have a rollback plan in case of issues

## Support

For issues or questions about JWT authentication:

1. **Check Documentation**: Review this document for common issues
2. **Log Files**: Check the application logs for detailed error information
3. **Community**: Join the MediaMTX community for support
4. **Contact**: Contact the development team if issues persist

## License

This documentation is provided under the same license as the MediaMTX Dashboard project. See the project root for the full license text.

---

*Last Updated: $(date +%Y-%m-%d)*
*Version: 1.0*