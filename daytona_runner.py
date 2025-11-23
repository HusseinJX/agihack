"""
Daytona Job Runner for Fly-Out Workflow

This module handles spinning up Daytona workspaces to execute the workflow in isolation.
"""

import os
import requests
import json
import time
from typing import Dict, Any, Optional


def run_in_daytona(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Spin up a Daytona workspace/job to execute the workflow in isolation.
    
    Args:
        params: Workflow parameters including:
            - from_location: Origin city/airport
            - to: Destination city/airport
            - depart_date: Departure date
            - eat_mode: "in" or "out"
            - lodging: "airbnb" or "marriott"
            - num_travelers: Number of travelers
    
    Returns:
        dict with workflow results from Daytona job execution
    """
    # Daytona configuration
    DAYTONA_API_URL = os.getenv("DAYTONA_API_URL", "http://localhost:3000/api/v1")
    DAYTONA_API_KEY = os.getenv("DAYTONA_API_KEY", "")
    DAYTONA_WORKSPACE_TEMPLATE = os.getenv("DAYTONA_WORKSPACE_TEMPLATE", "flyout-workflow")
    
    if not DAYTONA_API_KEY:
        print("Warning: DAYTONA_API_KEY not set, running workflow locally")
        # Fallback: import and run locally
        from vendor_agent import run_flyout_workflow
        return run_flyout_workflow(params)
    
    try:
        # Step 1: Create Daytona workspace
        print("Creating Daytona workspace...")
        workspace_name = f"flyout-{int(time.time())}"
        
        workspace_config = {
            "name": workspace_name,
            "template": DAYTONA_WORKSPACE_TEMPLATE,
            "project": "flyout-workflow",
            "env": {
                "WORKFLOW_PARAMS": json.dumps(params),
                "AGI_API_KEY": os.getenv("AGI_API_KEY", ""),
                "MINIMAX_API_KEY": os.getenv("MINIMAX_API_KEY", ""),
                "TELNYX_API_KEY": os.getenv("TELNYX_API_KEY", ""),
                "TELNYX_PHONE_NUMBER": os.getenv("TELNYX_PHONE_NUMBER", ""),
                "RECIPIENT_PHONE": os.getenv("RECIPIENT_PHONE", "6287345655"),
            }
        }
        
        headers = {
            "Authorization": f"Bearer {DAYTONA_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Create workspace
        create_resp = requests.post(
            f"{DAYTONA_API_URL}/workspace",
            headers=headers,
            json=workspace_config,
            timeout=60
        )
        create_resp.raise_for_status()
        workspace_data = create_resp.json()
        workspace_id = workspace_data.get("id") or workspace_name
        
        print(f"Workspace created: {workspace_id}")
        
        # Step 2: Wait for workspace to be ready
        print("Waiting for workspace to be ready...")
        max_wait = 120  # 2 minutes
        waited = 0
        while waited < max_wait:
            status_resp = requests.get(
                f"{DAYTONA_API_URL}/workspace/{workspace_id}",
                headers=headers,
                timeout=30
            )
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                if status_data.get("status") == "running":
                    break
            time.sleep(2)
            waited += 2
        
        if waited >= max_wait:
            raise Exception("Workspace did not become ready in time")
        
        # Step 3: Execute workflow command in workspace
        print("Executing workflow in Daytona workspace...")
        command = "python vendor_agent.py --execute-workflow"
        
        exec_resp = requests.post(
            f"{DAYTONA_API_URL}/workspace/{workspace_id}/command",
            headers=headers,
            json={"command": command},
            timeout=300  # 5 minutes for workflow execution
        )
        exec_resp.raise_for_status()
        exec_data = exec_resp.json()
        
        # Step 4: Stream logs/output
        print("Streaming workflow output...")
        if exec_data.get("output"):
            print(exec_data["output"])
        
        # Step 5: Get results
        # The workflow should write results to a file or return via API
        # For now, we'll parse the output
        result = {
            "success": True,
            "workspace_id": workspace_id,
            "output": exec_data.get("output", ""),
            "timeline": [],
            "state_log": []
        }
        
        # Try to parse JSON from output if available
        try:
            if exec_data.get("output"):
                # Look for JSON in output
                output_lines = exec_data["output"].split("\n")
                for line in output_lines:
                    if line.strip().startswith("{") and "timeline" in line:
                        parsed = json.loads(line.strip())
                        result.update(parsed)
        except Exception as e:
            print(f"Warning: Could not parse output as JSON: {e}")
        
        # Step 6: Cleanup workspace (optional - you might want to keep it for debugging)
        cleanup = os.getenv("DAYTONA_CLEANUP", "true").lower() == "true"
        if cleanup:
            print(f"Cleaning up workspace {workspace_id}...")
            try:
                delete_resp = requests.delete(
                    f"{DAYTONA_API_URL}/workspace/{workspace_id}",
                    headers=headers,
                    timeout=30
                )
                delete_resp.raise_for_status()
                print("Workspace cleaned up")
            except Exception as e:
                print(f"Warning: Could not cleanup workspace: {e}")
        
        return result
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Daytona API request failed: {str(e)}"
        print(f"ERROR: {error_msg}")
        # Fallback to local execution
        print("Falling back to local workflow execution...")
        from vendor_agent import run_flyout_workflow
        return run_flyout_workflow(params)
    except Exception as e:
        error_msg = f"Daytona execution failed: {str(e)}"
        print(f"ERROR: {error_msg}")
        # Fallback to local execution
        print("Falling back to local workflow execution...")
        from vendor_agent import run_flyout_workflow
        return run_flyout_workflow(params)

