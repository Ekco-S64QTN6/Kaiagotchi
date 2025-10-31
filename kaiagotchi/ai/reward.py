from kaiagotchi.mesh import wifi
from typing import Dict


class RewardFunction:
    """Reward function for Kaiagotchi reinforcement learning."""
    
    # Reward configuration - should eventually move to config
    REWARD_WEIGHTS = {
        'handshake': 1.0,
        'activity': 0.2,
        'channel_diversity': 0.1,
        'blindness': -0.3,
        'missed_interactions': -0.3,
        'inactivity': -0.2,
        'sadness': -0.2,
        'boredom': -0.1
    }
    
    # Small value to avoid division by zero
    EPSILON: float = 1e-20
    
    # Expected reward range for normalization
    reward_range: tuple[float, float] = (-0.7, 1.02)

    def __call__(self, epoch_n: int, state: Dict[str, float]) -> float:
        """Calculate reward based on current state and performance."""
        
        tot_epochs: float = epoch_n + self.EPSILON
        tot_interactions: float = max(
            state['num_deauths'] + state['num_associations'], 
            state['num_handshakes']
        ) + self.EPSILON
        
        tot_channels: int = wifi.NumChannels

        # Positive rewards
        handshake_reward = self.REWARD_WEIGHTS['handshake'] * (
            state['num_handshakes'] / tot_interactions
        )
        activity_reward = self.REWARD_WEIGHTS['activity'] * (
            state['active_for_epochs'] / tot_epochs
        )
        channel_reward = self.REWARD_WEIGHTS['channel_diversity'] * (
            state['num_hops'] / tot_channels
        )

        # Negative rewards
        blindness_penalty = self.REWARD_WEIGHTS['blindness'] * (
            state['blind_for_epochs'] / tot_epochs
        )
        missed_penalty = self.REWARD_WEIGHTS['missed_interactions'] * (
            state['missed_interactions'] / tot_interactions
        )
        inactivity_penalty = self.REWARD_WEIGHTS['inactivity'] * (
            state['inactive_for_epochs'] / tot_epochs
        )

        # Emotional penalties (only apply after 5 epochs)
        sad_epochs = state['sad_for_epochs'] if state['sad_for_epochs'] >= 5 else 0
        bored_epochs = state['bored_for_epochs'] if state['bored_for_epochs'] >= 5 else 0
        
        sadness_penalty = self.REWARD_WEIGHTS['sadness'] * (sad_epochs / tot_epochs)
        boredom_penalty = self.REWARD_WEIGHTS['boredom'] * (bored_epochs / tot_epochs)

        total_reward = (
            handshake_reward + activity_reward + channel_reward +
            blindness_penalty + missed_penalty + inactivity_penalty +
            sadness_penalty + boredom_penalty
        )
        
        return total_reward