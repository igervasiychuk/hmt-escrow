---
name: Add a new EVM network
about: I want to begin the process to add a new evm network to hmt-escrow
title: ''
labels: feature
assignees: posix4e

---

HMT-Escrow supports arbitrary EVM networks but there's a bit of work to do to make a network first class and make sure that it works. All of our EVM network launches are supported by gitcoin but you can gain a yearly bonus by being our network sponsor. If you need support please join tech-discussions on the human protocol discord linked on hmt.ai.

### Steps to receive gitcoin bounty
- [ ] Suggest and have us authorize your bridging strategy. After all we need to bridge HMT over to the new network. Usually we need to use a erc20 compatible approach.
- [ ] Launch the contracts on the devnet and make sure that everything is working
- [ ] Launch contracts on production network and file a commit with all the contract information to this repo's documentation. Here's an example https://github.com/humanprotocol/hmt-escrow/pull/296
* [ ] Launch KVstore contracts https://github.com/humanprotocol/eth-kvstore
- [ ] Add the contracts to the relevant network scanner (etherscan equivalent) 
- [ ] Launch a working app on the network. The easiest one to get going is our example fortune. https://github.com/humanprotocol/fortune  Make a video of the functionality of the app working on the new network and link to relevant scanner transactions.
- [ ] Add to human dashboard [ https://dashboard.humanprotocol.org/ ]
- [ ] Request to become the maintainer for your EVM network. We will list you on our repo, give you an extra reward (generally around 1 ETH per year) and invite you to conferences. We will celebrate your name forever!
- [ ] Verify bridging of tokens works
### High level rules to make sure that you are doing this correctly
- [ ] We never want to create a mintable token. Your change should not change the total token supply from 1 billion
- [ ] When deploying production contracts use a dedicated wallet with a seed phrase you don't use anywhere else. You might be required to share it with us. 
