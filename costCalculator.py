import pandas as pd
import numpy as np

def calculate_rekognition_costs(
    num_students=1000,
    school_days=240,
    hours_per_day=2,  # Assuming peak hours during entry/exit
    fps=30,
    process_every_nth_frame=30,
    rekognition_cooldown=2,
    daily_api_call_limit=10000,
    include_storage=True
):
    """
    Calculate AWS Rekognition costs for face recognition attendance system
    """
    # Basic calculations
    seconds_per_day = hours_per_day * 3600
    total_frames_per_day = seconds_per_day * fps
    processed_frames_per_day = total_frames_per_day / process_every_nth_frame
    
    # Maximum possible API calls based on cooldown
    max_calls_per_day_cooldown = seconds_per_day / rekognition_cooldown
    
    # Actual API calls will be minimum of all limitations
    actual_api_calls_per_day = min(
        max_calls_per_day_cooldown,
        daily_api_call_limit,
        processed_frames_per_day
    )
    
    # Calculate monthly and annual stats
    monthly_api_calls = (actual_api_calls_per_day * school_days / 12)
    annual_api_calls = actual_api_calls_per_day * school_days
    
    # Cost tiers (Singapore region)
    tier1_limit = 1_000_000  # First 1M images: $0.0013
    tier2_limit = 5_000_000  # Next 4M images: $0.001
    tier3_limit = 35_000_000 # Next 30M images: $0.0008
    
    # Calculate costs per tier
    def calculate_tier_cost(calls):
        tier1_cost = min(calls, tier1_limit) * 0.0013
        remaining_after_tier1 = max(0, calls - tier1_limit)
        
        tier2_cost = min(remaining_after_tier1, tier2_limit - tier1_limit) * 0.001
        remaining_after_tier2 = max(0, remaining_after_tier1 - (tier2_limit - tier1_limit))
        
        tier3_cost = min(remaining_after_tier2, tier3_limit - tier2_limit) * 0.0008
        remaining_after_tier3 = max(0, remaining_after_tier2 - (tier3_limit - tier2_limit))
        
        tier4_cost = remaining_after_tier3 * 0.0005
        
        return tier1_cost + tier2_cost + tier3_cost + tier4_cost
    
    # Storage costs
    monthly_storage_cost = num_students * 0.0000125 if include_storage else 0
    annual_storage_cost = monthly_storage_cost * 12
    
    # Calculate monthly and annual API costs
    monthly_api_cost = calculate_tier_cost(monthly_api_calls)
    annual_api_cost = calculate_tier_cost(annual_api_calls)
    
    # Create results DataFrame
    results = pd.DataFrame({
        'Parameter': [
            'Process Every Nth Frame',
            'Rekognition Cooldown (s)',
            'Daily API Call Limit',
            'Frames Per Second',
            'School Days Per Year',
            'Peak Hours Per Day',
            'Number of Students',
            'Total Frames Per Day',
            'Processed Frames Per Day',
            'Actual API Calls Per Day',
            'Monthly API Calls',
            'Annual API Calls',
            'Monthly API Cost (USD)',
            'Monthly Storage Cost (USD)',
            'Total Monthly Cost (USD)',
            'Annual API Cost (USD)',
            'Annual Storage Cost (USD)',
            'Total Annual Cost (USD)'
        ],
        'Value': [
            process_every_nth_frame,
            rekognition_cooldown,
            daily_api_call_limit,
            fps,
            school_days,
            hours_per_day,
            num_students,
            f"{total_frames_per_day:,.0f}",
            f"{processed_frames_per_day:,.0f}",
            f"{actual_api_calls_per_day:,.0f}",
            f"{monthly_api_calls:,.0f}",
            f"{annual_api_calls:,.0f}",
            f"${monthly_api_cost:,.2f}",
            f"${monthly_storage_cost:,.2f}",
            f"${monthly_api_cost + monthly_storage_cost:,.2f}",
            f"${annual_api_cost:,.2f}",
            f"${annual_storage_cost:,.2f}",
            f"${annual_api_cost + annual_storage_cost:,.2f}"
        ]
    })
    
    return results

# Example usage
default_results = calculate_rekognition_costs()
print(default_results.to_string(index=False))