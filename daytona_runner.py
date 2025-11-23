from daytona import Daytona, DaytonaConfig
  
# Define the configuration
config = DaytonaConfig(api_key="dtn_652ec49b58abab4e2e70f6ab37aec6bcf3e49a9e79e691d1f3f31969c462dea5")

# Initialize the Daytona client
daytona = Daytona(config)

# Create the Sandbox instance
sandbox = daytona.create()

# Run the code securely inside the Sandbox
response = sandbox.process.code_run('print("Hello World from code!")')
if response.exit_code != 0:
  print(f"Error: {response.exit_code} {response.result}")
else:
    print(response.result)
  