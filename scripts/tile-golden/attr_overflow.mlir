cuda_tile.module @m {
  entry @attr_overflow(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %15 = make_tensor_view %14, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %19 = addi %12, %17 overflow<no_signed_wrap> : tile<128xi32>
    %20 = reshape %19 : tile<128xi32> -> tile<1x1x128xi32>
    %21, %22, %23 = get_num_tile_blocks : tile<i32>
    %24 = constant <i32: 1> : tile<i32>
    %25 = muli %21, %24 : tile<i32>
    %26 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %27 = make_tensor_view %26, shape = [%25, 3, 128], strides = [384, 128, 1] : tile<i32> -> tensor_view<?x3x128xi32, strides=[384, 128, 1]>
    %28 = make_partition_view %27 : partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x3x128xi32, strides=[384, 128, 1]>, dim_map=[0, 1, 2]>
    %29, %30, %31 = get_tile_block_id : tile<i32>
    %32, %33, %34 = get_tile_block_id : tile<i32>
    %35 = constant <i32: 4> : tile<i32>
    %36 = muli %30, %35 : tile<i32>
    %37 = store_view_tko weak %20, %28[%9, %36, %34] token=%18 : tile<1x1x128xi32>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x3x128xi32, strides=[384, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %38 = subi %12, %17 overflow<no_unsigned_wrap> : tile<128xi32>
    %39 = reshape %38 : tile<128xi32> -> tile<1x1x128xi32>
    %40 = constant <i32: 4> : tile<i32>
    %41 = muli %30, %40 : tile<i32>
    %42 = constant <i32: 1> : tile<i32>
    %43 = addi %41, %42 : tile<i32>
    %44 = store_view_tko weak %39, %28[%9, %43, %34] token=%37 : tile<1x1x128xi32>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x3x128xi32, strides=[384, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %45 = muli %12, %17 overflow<no_wrap> : tile<128xi32>
    %46 = reshape %45 : tile<128xi32> -> tile<1x1x128xi32>
    %47 = constant <i32: 4> : tile<i32>
    %48 = muli %30, %47 : tile<i32>
    %49 = constant <i32: 2> : tile<i32>
    %50 = addi %48, %49 : tile<i32>
    %51 = store_view_tko weak %46, %28[%9, %50, %34] token=%44 : tile<1x1x128xi32>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x3x128xi32, strides=[384, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
