from proxy_encoder import ProxyCall, encode_proxy_transaction_data
from proxy_signer import ProxyContractConfig, build_proxy_transaction_request


def test_proxy_signature_matches_official_vector() -> None:
    private_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    signer_address = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    usdc = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    approve_calldata = (
        "0x095ea7b30000000000000000000000004d97dcd97ec945f40cf65f87097ace5ea0476045"
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )

    proxy_data = encode_proxy_transaction_data(
        [ProxyCall(type_code=1, to=usdc, value="0", data=approve_calldata)]
    )

    request = build_proxy_transaction_request(
        private_key=private_key,
        from_address=signer_address,
        proxy_tx_data=proxy_data,
        nonce="0",
        relay_address="0xae700edfd9ab986395f3999fe11177b9903a52f1",
        proxy_config=ProxyContractConfig(
            proxy_factory="0xaB45c5A4B0c941a2F231C04C3f49182e1A254052",
            relay_hub="0xD216153c06E857cD7f72665E0aF1d7D82172F494",
        ),
        gas_price="0",
        gas_limit="85338",
    )

    assert (
        request.signature
        == "0x4c18e2d2294a00d686714aff8e7936ab657cb4655dfccb2b556efadcb7e835f8"
        "00dc2fecec69c501e29bb36ecb54b4da6b7c410c4dc740a33af2afde2b77297e1b"
    )

