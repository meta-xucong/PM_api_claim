from safe_signer import SafeContractConfig, build_safe_transaction_request


def test_safe_signature_matches_official_vector() -> None:
    private_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    signer_address = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    usdc = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    approve_calldata = (
        "0x095ea7b30000000000000000000000004d97dcd97ec945f40cf65f87097ace5ea0476045"
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )

    request = build_safe_transaction_request(
        private_key=private_key,
        from_address=signer_address,
        to_address=usdc,
        calldata=approve_calldata,
        nonce="0",
        chain_id=137,
        safe_config=SafeContractConfig(
            safe_factory="0xaacFeEa03eb1561C4e67d661e40682Bd20E3541b",
            safe_multisend="0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761",
        ),
    )

    assert (
        request.signature
        == "0xf368488355b0566e99eff3bccc35e98b77d8f3a6e6866176188488c34f0305b0"
        "7e4a4c600c7a1592e4ac1e96b5887ebff2cb26987a3ad501006b39944df098c21f"
    )

