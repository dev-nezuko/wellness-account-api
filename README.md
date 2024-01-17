# Fitness Auth App

This Django application provides authentication functionality through AWS Cognito, using a GraphQL endpoint. It is designed to streamline the process of user authentication and management in a fitness application context.

## Key Features

- **Mutations**:
  - **SignIn**: Allows users to sign in to AWS Cognito. Returns user records along with an authorization token for accessing other endpoints.
  - **SignUp**: Facilitates the creation of new user accounts.
  - **UserConfirmation**: Enables new users to confirm their account using an OTP sent to their email.

- **Query**:
  - **GetUser**: Fetches the record of a specific user, providing essential user details.

## Built With

- **Framework**: Python 3
  - Leverages the robust and versatile capabilities of Python 3 to ensure smooth and efficient backend operations.

## Getting Started

To get a local copy up and running, follow these simple steps.

### Prerequisites

- **Python**: The application is built with Python. Ensure you have Python 3 installed on your system.
- **pip**: You'll need pip for installing Python packages. It usually comes with Python.

### Installation

1. **Clone the Repository**:
   Start by cloning the repository to your local machine:
   
   ```bash
   git clone https://github.com/dev-nezuko/wellness-account-api.git
   cd repo
   ```

2. **Set Up Environment Variables**:
   Create a `.env` file to store your configuration:
   
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and fill in your AWS credentials.

3. **Install Dependencies**:
   Install the required Python libraries for the project:
   
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Server**:
   Launch the application locally:
   
   ```bash
   python manage.py runserver
   ```
   The server will start, typically on `http://localhost:8000`. You can access the GraphQL endpoint at `http://localhost:8000/graphql`.
