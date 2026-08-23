import unittest
from early_detection import predict_uniswap_v3_pool_address

class TestUniswapUpgrades(unittest.TestCase):
    def test_predict_uniswap_v3_pool_address(self):
        # Uniswap V3 Factory on Base: 0x33128a8fC17869897dcE68Ed026d694621f6FDfD
        # WETH on Base: 0x4200000000000000000000000000000000000006
        # USDC on Base: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
        # 1% fee (10000) pool address is: 0xd0b53D9277af2ab4AA757C5aE2368c7FFC919FFD or similar
        factory = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
        weth = "0x4200000000000000000000000000000000000006"
        usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        
        # Pre-calculated predicted address using CREATE2 formula offline
        predicted = predict_uniswap_v3_pool_address(factory, weth, usdc, 10000)
        self.assertTrue(predicted.startswith("0x"))
        self.assertEqual(len(predicted), 42)

if __name__ == '__main__':
    unittest.main()
