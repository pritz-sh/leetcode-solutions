class Solution:
    def plusOne(self, digits: List[int]) -> List[int]:
        temp=0
        for i in digits:
            temp=(temp*10)+i
        temp+=1
        res = [int(x) for x in str(temp)]
        return res