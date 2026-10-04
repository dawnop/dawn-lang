cuda_tile.module @m {
  entry @attr_memsem(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 384> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8, %9, %10 = get_num_tile_blocks : tile<i32>
    %11 = constant <i32: 128> : tile<i32>
    %12 = muli %8, %11 : tile<i32>
    %13 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %14 = make_tensor_view %13, shape = [%12], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %15[%16] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %21 = reshape %7 : tile<i32> -> tile<1xi32>
    %22 = broadcast %21 : tile<1xi32> -> tile<128xi32>
    %23 = iota : tile<128xi32>
    %24 = addi %22, %23 : tile<128xi32>
    %25 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %26 = broadcast %25 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %27 = offset %26, %24 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %28, %29 = atomic_rmw_tko acquire tl_blk %27, add, %19 token=%20 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    %30 = constant <i32: 128> : tile<128xi32>
    %31 = addi %24, %30 : tile<128xi32>
    %32 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %33 = broadcast %32 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %34 = offset %33, %31 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %35, %36 = atomic_rmw_tko release sys %34, add, %19 token=%29 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    %37 = constant <i32: 256> : tile<128xi32>
    %38 = addi %24, %37 : tile<128xi32>
    %39 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %40 = broadcast %39 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %41 = offset %40, %38 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %42, %43 = atomic_rmw_tko acq_rel device %41, add, %19 token=%36 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xi32>, token
    return
  }
}
