cuda_tile.module @m {
  entry @insert_tile(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %7 = broadcast %6 : tile<1x1xi32> -> tile<16x8xi32>
    %8 = iota : tile<16xi32>
    %9 = reshape %8 : tile<16xi32> -> tile<16x1xi32>
    %10 = broadcast %9 : tile<16x1xi32> -> tile<16x8xi32>
    %11 = constant <i32: 8> : tile<16x8xi32>
    %12 = muli %10, %11 : tile<16x8xi32>
    %13 = addi %7, %12 : tile<16x8xi32>
    %14 = iota : tile<8xi32>
    %15 = reshape %14 : tile<8xi32> -> tile<1x8xi32>
    %16 = broadcast %15 : tile<1x8xi32> -> tile<16x8xi32>
    %17 = addi %13, %16 : tile<16x8xi32>
    %18 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %19 = broadcast %18 : tile<1x1xptr<f64>> -> tile<16x8xptr<f64>>
    %20 = offset %19, %17 : tile<16x8xptr<f64>>, tile<16x8xi32> -> tile<16x8xptr<f64>>
    %21, %22 = load_ptr_tko weak %20 token=%0 : tile<16x8xptr<f64>> -> tile<16x8xf64>, token
    %23 = constant <i32: 1> : tile<i32>
    %24 = constant <i32: 0> : tile<i32>
    %25 = extract %21[%23, %24] : tile<16x8xf64> -> tile<8x4xf64>
    %26 = constant <i32: 1> : tile<i32>
    %27 = constant <i32: 0> : tile<i32>
    %28 = insert %25, %21[%26, %27] : tile<8x4xf64>, tile<16x8xf64>
    %29, %30, %31 = get_num_tile_blocks : tile<i32>
    %32 = constant <i32: 32> : tile<i32>
    %33 = muli %29, %32 : tile<i32>
    %34 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %35 = make_tensor_view %34, shape = [%33, 8], strides = [8, 1] : tile<i32> -> tensor_view<?x8xf64, strides=[8, 1]>
    %36 = make_partition_view %35 : partition_view<tile=(16x8), padding_value = zero, tensor_view<?x8xf64, strides=[8, 1]>, dim_map=[0, 1]>
    %37, %38, %39 = get_tile_block_id : tile<i32>
    %40, %41, %42 = get_tile_block_id : tile<i32>
    %43 = constant <i32: 2> : tile<i32>
    %44 = muli %37, %43 : tile<i32>
    %45 = store_view_tko weak %28, %36[%44, %41] token=%22 : tile<16x8xf64>, partition_view<tile=(16x8), padding_value = zero, tensor_view<?x8xf64, strides=[8, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %46 = constant <i32: 0> : tile<i32>
    %47 = constant <i32: 1> : tile<i32>
    %48 = insert %25, %21[%46, %47] : tile<8x4xf64>, tile<16x8xf64>
    %49 = constant <i32: 2> : tile<i32>
    %50 = muli %37, %49 : tile<i32>
    %51 = constant <i32: 1> : tile<i32>
    %52 = addi %50, %51 : tile<i32>
    %53 = store_view_tko weak %48, %36[%52, %41] token=%45 : tile<16x8xf64>, partition_view<tile=(16x8), padding_value = zero, tensor_view<?x8xf64, strides=[8, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
