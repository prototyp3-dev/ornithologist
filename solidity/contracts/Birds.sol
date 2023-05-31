// SPDX-License-Identifier: MIT
pragma solidity ^0.8.4;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Counters.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@cartesi/rollups/contracts/interfaces/IInput.sol";


contract Birds is Ownable, ERC721URIStorage {
    // Owner of the contract should be the DApp address

    using Counters for Counters.Counter;

    Counters.Counter private _currentReqId;
    Counters.Counter private _tokenIds;

    // W3bstream operator address
    address public operatorAddress = address(0);

    // This event serves as a request for birdwatch activity
    event ActivityRequested (
        uint256 _requestId,
        uint256 _time,
        address _userAddress,
        string _deviceId); 

    // send this contract address to Cartesi DApp
    function sendBirdAddress() external returns (bytes32) {
        
        uint8 actionIndex = 0;

        bytes memory input = abi.encodePacked(
            actionIndex,
            msg.sig
        );

        return IInput(this.owner()).addInput(input);
    }

    // update operator address
    function setOperatorAddress(address _newOperatorAddress) external onlyOwner {
        operatorAddress = _newOperatorAddress;
    }

    // Attempt to claim rewards for birdwatch activity for a specific device
    function reportBirdwatch(string calldata _deviceId) public returns (bool) {

        // Emit a new W3bStream request to get an index of user's birdwatch activity
        uint256 reqId = _currentReqId.current();       

        // Emit the request to W3bStream
        emit ActivityRequested(reqId, block.timestamp, msg.sender, _deviceId);

        _currentReqId.increment();
        return true;
    }

    // Response from W3bStream
    function addInput(bytes calldata _input) public returns (bytes32) {
        require(operatorAddress == msg.sender, "Only operator can add inputs");
        uint8 actionIndex = 1;

        bytes memory input = abi.encodePacked(
            actionIndex,
            _input
        );

        return IInput(this.owner()).addInput(input);
    }


    //////
    // ERC 721 functions

    constructor() Ownable() ERC721("BirdNFT", "BNFT") {}

    // Mint and inform the dapp about the id
    function mint(address recipient, string memory birdId) public onlyOwner returns (bytes32) {
        _tokenIds.increment();

        uint256 newItemId = _tokenIds.current();
        _mint(recipient, newItemId);
        _setTokenURI(newItemId, birdId);

        uint8 actionIndex = 2;

        bytes memory input = abi.encodePacked(
            actionIndex,
            newItemId,
            birdId
        );

        return IInput(this.owner()).addInput(input);
    }
    
}