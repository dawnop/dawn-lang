cuda_tile.module @m {
  entry @assert_pass(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %11 = broadcast %10 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %12 = offset %11, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<i32>> -> tile<128xi32>, token
    %15 = constant <i32: 1000> : tile<128xi32>
    %16 = cmpi less_than %13, %15, signed : tile<128xi32> -> tile<128xi1>
    assert %16, "tile-golden: a lane reached the limit" : tile<128xi1>
    %17 = constant <i32: 1> : tile<128xi32>
    %18 = addi %13, %17 : tile<128xi32>
    %19 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %20 = broadcast %19 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %21 = offset %20, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %22 = store_ptr_tko weak %21, %18 token=%14 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
