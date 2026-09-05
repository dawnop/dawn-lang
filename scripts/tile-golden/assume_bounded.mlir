cuda_tile.module @m {
  entry @assume_bounded(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
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
    %15 = assume bounded<0, 100000>, %13 : tile<128xi32>
    %16 = constant <i32: 5> : tile<128xi32>
    %17 = addi %15, %16 : tile<128xi32>
    %18 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %19 = broadcast %18 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %20 = offset %19, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %21 = store_ptr_tko weak %20, %17 token=%14 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
