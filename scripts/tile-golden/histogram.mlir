cuda_tile.module @m {
  entry @histogram(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [500], strides = [1] : tensor_view<500xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(64), padding_value = zero, tensor_view<500xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<500xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xi32>, token
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 64> : tile<i32>
    %13 = muli %9, %12 : tile<i32>
    %14 = reshape %13 : tile<i32> -> tile<1xi32>
    %15 = broadcast %14 : tile<1xi32> -> tile<64xi32>
    %16 = iota : tile<64xi32>
    %17 = addi %15, %16 : tile<64xi32>
    %18 = constant <i32: 500> : tile<64xi32>
    %19 = cmpi less_than %17, %18, signed : tile<64xi32> -> tile<64xi1>
    %20 = constant <i32: 0> : tile<64xi32>
    %21 = cmpi greater_than_or_equal %7, %20, signed : tile<64xi32> -> tile<64xi1>
    %22 = constant <i32: 16> : tile<64xi32>
    %23 = cmpi less_than %7, %22, signed : tile<64xi32> -> tile<64xi1>
    %24 = constant <i1: 0> : tile<64xi1>
    %25 = select %21, %23, %24 : tile<64xi1>, tile<64xi1>
    %26 = constant <i1: 0> : tile<64xi1>
    %27 = select %19, %25, %26 : tile<64xi1>, tile<64xi1>
    %28 = constant <i32: 15> : tile<64xi32>
    %29 = andi %7, %28 : tile<64xi32>
    %30 = constant <i32: 1> : tile<64xi32>
    %31 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %32 = broadcast %31 : tile<1xptr<i32>> -> tile<64xptr<i32>>
    %33 = offset %32, %29 : tile<64xptr<i32>>, tile<64xi32> -> tile<64xptr<i32>>
    %34, %35 = atomic_rmw_tko relaxed device %33, add, %30, %27 token=%8 : tile<64xptr<i32>>, tile<64xi32>, tile<64xi1> -> tile<64xi32>, token
    return
  }
}
