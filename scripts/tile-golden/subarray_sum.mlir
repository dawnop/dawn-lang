cuda_tile.module @m {
  entry @subarray_sum(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 137> : tile<1024xi32>
    %11 = cmpi greater_than_or_equal %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <i32: 902> : tile<1024xi32>
    %13 = cmpi less_than %9, %12, signed : tile<1024xi32> -> tile<1024xi1>
    %14 = constant <i1: 0> : tile<1024xi1>
    %15 = select %11, %13, %14 : tile<1024xi1>, tile<1024xi1>
    %16 = constant <i32: 0> : tile<1024xi32>
    %17 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %18 = broadcast %17 : tile<1xptr<i32>> -> tile<1024xptr<i32>>
    %19 = offset %18, %9 : tile<1024xptr<i32>>, tile<1024xi32> -> tile<1024xptr<i32>>
    %20, %21 = load_ptr_tko weak %19, %15, %16 token=%0 : tile<1024xptr<i32>>, tile<1024xi1>, tile<1024xi32> -> tile<1024xi32>, token
    %22 = reduce %20 dim=0 identities=[0 : i32] : tile<1024xi32> -> tile<i32> (%23: tile<i32>, %24: tile<i32>) {
      %25 = addi %23, %24 : tile<i32>
      yield %25 : tile<i32>
    }
    %26 = constant <i32: 1> : tile<i32>
    %27 = muli %1, %26 : tile<i32>
    %28 = reshape %22 : tile<i32> -> tile<1xi32>
    %29 = broadcast %28 : tile<1xi32> -> tile<1xi32>
    %30 = reshape %27 : tile<i32> -> tile<1xi32>
    %31 = broadcast %30 : tile<1xi32> -> tile<1xi32>
    %32 = iota : tile<1xi32>
    %33 = addi %31, %32 : tile<1xi32>
    %34 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %35 = broadcast %34 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %36 = offset %35, %33 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %37 = store_ptr_tko weak %36, %29 token=%21 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
