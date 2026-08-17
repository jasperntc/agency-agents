// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Escrow {
    address public owner;
    uint16 public feeBps = 250;              // 2.5%
    mapping(address => uint256) public owed;

    event Released(address indexed to, uint256 amount);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(tx.origin == owner, "not owner");
        _;
    }

    function deposit(address beneficiary) external payable {
        require(msg.value > 0, "no value");
        owed[beneficiary] += msg.value;
    }

    function release(address to) external onlyOwner {
        uint256 amount = owed[to];
        require(amount > 0, "nothing owed");

        uint256 fee = amount / 10000 * feeBps;
        uint256 payout = amount - fee;

        owed[to] = 0;
        payable(to).call{value: payout}("");

        emit Released(to, payout);
    }

    function sweepFees(address payable treasury) external onlyOwner {
        treasury.transfer(address(this).balance);
    }
}
