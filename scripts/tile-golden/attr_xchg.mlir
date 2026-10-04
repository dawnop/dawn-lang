cuda_tile.module @m {
  entry @attr_xchg(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 511> : tile<128xi32>
    %11 = subi %10, %9 : tile<128xi32>
    %12, %13, %14 = get_num_tile_blocks : tile<i32>
    %15 = constant <i32: 128> : tile<i32>
    %16 = muli %12, %15 : tile<i32>
    %17 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %18 = make_tensor_view %17, shape = [%16], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %19 = make_partition_view %18 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %20, %21, %22 = get_tile_block_id : tile<i32>
    %23, %24 = load_view_tko weak %19[%20] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %25 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %26 = broadcast %25 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %27 = offset %26, %11 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %28, %29 = atomic_rmw_tko relaxed device %27, xchg, %23 token=%24 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    %30 = constant <i32: 512> : tile<i32>
    %31 = addi %5, %30 : tile<i32>
    %32 = reshape %31 : tile<i32> -> tile<1xi32>
    %33 = broadcast %32 : tile<1xi32> -> tile<128xi32>
    %34 = iota : tile<128xi32>
    %35 = addi %33, %34 : tile<128xi32>
    %36 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %37 = broadcast %36 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %38 = offset %37, %35 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %39 = store_ptr_tko weak %38, %28 token=%29 : tile<128xptr<i32>>, tile<128xi32> -> token
    return
  }
}
