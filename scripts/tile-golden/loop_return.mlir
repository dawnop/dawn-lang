cuda_tile.module @m {
  entry @loop_return(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = constant <i32: 0> : tile<128xi32>
    %15, %16, %17 = loop iter_values(%18 = %12, %19 = %14, %20 = %13) : tile<128xi32>, tile<128xi32>, token -> (tile<128xi32>, tile<128xi32>, token) {
      %21 = constant <i32: 1> : tile<128xi32>
      %22 = addi %19, %21 : tile<128xi32>
      %23, %24, %25 = get_num_tile_blocks : tile<i32>
      %26 = constant <i32: 256> : tile<i32>
      %27 = muli %23, %26 : tile<i32>
      %28 = assume div_by<16>, %arg1 : tile<ptr<i32>>
      %29 = make_tensor_view %28, shape = [%27], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
      %30 = make_partition_view %29 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
      %31 = constant <i32: 2> : tile<i32>
      %32 = muli %9, %31 : tile<i32>
      %33 = store_view_tko weak %22, %30[%32] token=%20 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
      %34 = reduce %18 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%35: tile<i32>, %36: tile<i32>) {
        %37 = maxi %35, %36 signed : tile<i32>
        yield %37 : tile<i32>
      }
      %38 = constant <i32: 200> : tile<i32>
      %39 = cmpi less_than_or_equal %38, %34, signed : tile<i32> -> tile<i1>
      if %39 {
        return
      } else {
        yield
      }
      %40 = reduce %22 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%41: tile<i32>, %42: tile<i32>) {
        %43 = maxi %41, %42 signed : tile<i32>
        yield %43 : tile<i32>
      }
      %44 = constant <i32: 100> : tile<i32>
      %45 = cmpi less_than_or_equal %44, %40, signed : tile<i32> -> tile<i1>
      %46 = addi %18, %21 : tile<128xi32>
      if %45 {
        break %18, %19, %33 : tile<128xi32>, tile<128xi32>, token
      } else {
        yield
      }
      continue %46, %22, %33 : tile<128xi32>, tile<128xi32>, token
    }
    %47, %48, %49 = get_num_tile_blocks : tile<i32>
    %50 = constant <i32: 256> : tile<i32>
    %51 = muli %47, %50 : tile<i32>
    %52 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %53 = make_tensor_view %52, shape = [%51], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %54 = make_partition_view %53 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %55 = constant <i32: 2> : tile<i32>
    %56 = muli %9, %55 : tile<i32>
    %57 = constant <i32: 1> : tile<i32>
    %58 = addi %56, %57 : tile<i32>
    %59 = store_view_tko weak %15, %54[%58] token=%17 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
